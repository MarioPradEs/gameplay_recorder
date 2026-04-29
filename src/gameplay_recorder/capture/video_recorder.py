"""Video segment recorder for gameplay_recorder.

Handles `adb shell screenrecord` with the Android 180s hard limit by
segmenting recordings into 170s chunks. Each completed segment is pulled
from the device and deleted from /sdcard immediately.

Design: capture/video_recorder.py — VideoSegmentRecorder(QThread)
Signals: segment_started(int), segment_finished(int, Path), recording_error(str)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from gameplay_recorder.config import SEGMENT_DURATION_S

if TYPE_CHECKING:
    from gameplay_recorder.adb.connection import AdbConnection

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:  # allow unit tests without a display
    QThread = object  # type: ignore[assignment,misc]

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *args):
            pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_FREE_KB: int = 500_000  # 500 MB in KB
_DEVICE_SEG_DIR: str = "/sdcard"


# ---------------------------------------------------------------------------
# Pure helpers (pure functions — easy to unit-test without a Qt event loop)
# ---------------------------------------------------------------------------


def segment_path(index: int, device_dir: str = _DEVICE_SEG_DIR) -> Path:
    """Return the on-device path for segment *index* as a local Path object.

    The *name* attribute is stable cross-platform (seg_0.mp4, seg_1.mp4, ...).
    When sending to the Android device, convert via .as_posix() to get
    forward-slash separators regardless of host OS.

    Examples:
        segment_path(0).name  == 'seg_0.mp4'
        segment_path(1).name  == 'seg_1.mp4'
    """
    return Path(device_dir) / f"seg_{index}.mp4"


def check_free_space(adb_conn: AdbConnection) -> str | None:
    """Check available storage on /sdcard.

    Returns:
        None — if free space is >= 500 MB (recording can proceed).
        str  — human-readable error message if space is < 500 MB.

    Spec: Requirement 'Free-Space Pre-Check'.
    """
    try:
        output = adb_conn.shell("df /sdcard")
        # Parse last data line: field at index 3 is "Available" in KB.
        for line in reversed(output.strip().splitlines()):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    free_kb = int(parts[3])
                    if free_kb < _MIN_FREE_KB:
                        free_mb = free_kb // 1024
                        return (
                            f"Device storage low ({free_mb} MB free). "
                            "Free at least 500 MB before recording."
                        )
                    return None
                except ValueError:
                    continue
    except Exception:
        pass
    return None  # if we can't determine, allow the user to proceed


def _resolve_adb() -> str:
    """Return path to the adb binary (bundled or system)."""
    # PyInstaller bundle: sys._MEIPASS/adb[.exe]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for candidate in (
            Path(meipass) / "adb.exe",
            Path(meipass) / "adb",
        ):
            if candidate.exists():
                return str(candidate)
    # Fall back to system PATH
    found = shutil.which("adb")
    return found or "adb"


def _spawn_screenrecord(
    serial: str,
    device_path: str | Path,
    duration: int = SEGMENT_DURATION_S,
) -> subprocess.Popen[bytes]:
    """Spawn `adb -s SERIAL shell screenrecord --time-limit DURATION DEVICE_PATH`.

    Returns the Popen handle (non-blocking — caller manages lifecycle).

    Args:
        serial:      ADB device serial number.
        device_path: On-device recording path. Always kept as a POSIX string
                     because the path lives on the Android device, not the host.
                     Pass a str (preferred) or a pathlib.Path.
        duration:    Max recording duration in seconds (default: SEGMENT_DURATION_S).
    """
    # Ensure POSIX separators — the path is on Android, not Windows host
    if isinstance(device_path, Path):
        posix_path = device_path.as_posix()
    else:
        # Already a string — trust the caller used forward slashes
        posix_path = str(device_path)

    adb = _resolve_adb()
    cmd = [
        adb,
        "-s",
        serial,
        "shell",
        "screenrecord",
        "--time-limit",
        str(duration),
        posix_path,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pull_and_delete(
    adb_conn: AdbConnection,
    device_path: str,
    local_dir: Path,
) -> Path:
    """Pull a completed segment from the device then delete it from /sdcard.

    Args:
        adb_conn:    Connected AdbConnection instance (carries serial).
        device_path: On-device path string (e.g. '/sdcard/seg_0.mp4').
        local_dir:   Host directory to pull the file into.

    Returns:
        Path of the pulled local file.

    Spec: Requirement 'Segmented Video Capture', Scenario 'On-device cleanup'.
    """
    local_dir.mkdir(parents=True, exist_ok=True)
    adb = _resolve_adb()
    serial = getattr(adb_conn, "_serial", None) or ""

    # Pull the file to the local directory
    pull_cmd = (
        [adb, "-s", serial, "pull", device_path, str(local_dir)]
        if serial
        else [adb, "pull", device_path, str(local_dir)]
    )
    subprocess.run(pull_cmd, check=True, capture_output=True)

    # Delete from device
    adb_conn.shell(f"rm -f {device_path}")

    return local_dir / Path(device_path).name


# ---------------------------------------------------------------------------
# VideoSegmentRecorder — QThread worker
# ---------------------------------------------------------------------------


class VideoSegmentRecorder(QThread):
    """Record device screen in 170s segments, pulling each segment after completion.

    Signals:
        segment_started(int):            Emitted when segment N starts recording.
        segment_finished(int, Path):     Emitted when segment N is pulled to host.
        recording_error(str):            Emitted on any unrecoverable error.
    """

    segment_started = Signal(int)
    segment_finished = Signal(int, object)  # int, Path
    recording_error = Signal(str)

    def __init__(
        self,
        adb_conn: AdbConnection,
        local_dir: Path,
        duration: int = SEGMENT_DURATION_S,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._adb_conn = adb_conn
        self._local_dir = local_dir
        self._duration = duration
        self._segments: list[Path] = []

    # ── QThread entry point ──────────────────────────────────────────────────

    def run(self) -> None:
        """Main recording loop — runs in the worker thread."""
        segment_index = 0
        try:
            while not self.isInterruptionRequested():
                dev_path = segment_path(segment_index)
                self.segment_started.emit(segment_index)

                proc = _spawn_screenrecord(
                    self._adb_conn._serial or "",
                    dev_path,
                    duration=self._duration,
                )

                # Wait for this segment to finish (either time-limit or interruption)
                proc.wait()

                if self.isInterruptionRequested():
                    # Clean termination: pull whatever was recorded
                    local_file = pull_and_delete(self._adb_conn, str(dev_path), self._local_dir)
                    self._segments.append(local_file)
                    self.segment_finished.emit(segment_index, local_file)
                    break

                # Normal 170s segment completion — pull and start next
                local_file = pull_and_delete(self._adb_conn, str(dev_path), self._local_dir)
                self._segments.append(local_file)
                self.segment_finished.emit(segment_index, local_file)
                segment_index += 1

        except Exception as exc:
            self.recording_error.emit(str(exc))

    @property
    def segments(self) -> list[Path]:
        """Return list of pulled segment paths in recording order."""
        return list(self._segments)
