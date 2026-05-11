"""scrcpy-based video recorder for gameplay_recorder.

Records the device screen on the HOST using scrcpy v3.3.4.
Produces a single gameplay.mp4 file — no segmentation, no /sdcard access.

Design: capture/scrcpy_recorder.py — ScrcpyRecorder(QThread)
Signals: recording_started(), recording_finished(object), recording_error(str)
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

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

_TERMINATE_TIMEOUT_S: int = 5
_MP4_REGION_SIZE: int = 128 * 1024  # bytes to scan at head / tail


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _validate_mp4(path: Path) -> tuple[bool, str | None]:
    """Scan first/last 128 KB of an mp4 file for the moov atom signature.

    Reads ONLY the head and tail regions — avoids loading hundreds of MB.

    Returns:
        (True, None)         — moov bytes found; file is likely playable.
        (False, reason: str) — moov not found, file missing, or file empty.

    Edge cases handled:
        - File does not exist  → (False, "mp4 file missing")
        - File is 0 bytes      → (False, "mp4 file empty")
        - File < 256 KB        → scan whole file in one read (no two-region logic)
    """
    if not path.exists():
        return (False, "mp4 file missing")
    size = path.stat().st_size
    if size == 0:
        return (False, "mp4 file empty")
    with open(path, "rb") as f:
        if size <= _MP4_REGION_SIZE * 2:
            # Small file: scan the whole thing once
            data = f.read()
            if b"moov" in data:
                return (True, None)
            return (False, "no moov atom found")
        # Large file: scan head + tail independently
        head = f.read(_MP4_REGION_SIZE)
        if b"moov" in head:
            return (True, None)
        f.seek(-_MP4_REGION_SIZE, 2)  # 2 = SEEK_END
        tail = f.read(_MP4_REGION_SIZE)
        if b"moov" in tail:
            return (True, None)
    return (False, "no moov atom found")


def _resolve_scrcpy() -> str:
    """Return path to the scrcpy binary (bundled or system).

    Resolution order:
    1. PyInstaller bundle: sys._MEIPASS/scrcpy[.exe]
    2. System PATH via shutil.which
    3. Literal 'scrcpy' as last resort
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for candidate in (
            Path(meipass) / "scrcpy.exe",
            Path(meipass) / "scrcpy",
        ):
            if candidate.exists():
                return str(candidate)
    found = shutil.which("scrcpy")
    return found or "scrcpy"


def _spawn_scrcpy(
    serial: str,
    output_path: Path,
) -> subprocess.Popen[bytes]:
    """Spawn `scrcpy --serial SERIAL --record OUTPUT --no-playback --no-audio`.

    Returns the Popen handle (non-blocking — caller manages lifecycle).

    Args:
        serial:      ADB device serial number.
        output_path: Host-side path where gameplay.mp4 will be written.
    """
    scrcpy = _resolve_scrcpy()
    cmd = [
        scrcpy,
        "--serial",
        serial,
        "--record",
        str(output_path),
        "--no-playback",
        "--no-audio",
        "--time-limit=7200",
    ]
    logger.info(
        "ScrcpyRecorder: spawning scrcpy serial=%s output=%s",
        serial,
        output_path,
    )
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(cmd, **kwargs)


def check_host_free_space(output_dir: Path, min_gb: float = 1) -> str | None:
    """Check available storage on the host output directory.

    Returns:
        None — if free space is >= min_gb (recording can proceed).
        str  — human-readable error message if space is < min_gb.

    Spec: Requirement 'Free-Space Pre-Check' (Modified) — host disk, 1 GB threshold.
    Scenario 'Insufficient storage': message must say "<1 GB free in '<output_dir>'".

    Design decisions:
    - Uses shutil.disk_usage on the directory (or its parent if dir doesn't exist yet).
    - OSError is caught defensively — allows recording to proceed rather than blocking.
    - output_dir may not exist at check time (session_dir created lazily); fall back to parent.
    """
    check_path = output_dir if output_dir.exists() else output_dir.parent

    try:
        usage = shutil.disk_usage(check_path)
    except OSError:
        logger.warning(
            "check_host_free_space: could not query disk usage for %s — allowing recording",
            check_path,
        )
        return None

    min_bytes = min_gb * 1024**3
    if usage.free < min_bytes:
        return (
            f"Host disk space low (< {min_gb:g} GB free in '{output_dir}'). "
            "Free space before recording."
        )
    return None


# ---------------------------------------------------------------------------
# ScrcpyRecorder — QThread worker
# ---------------------------------------------------------------------------


class ScrcpyRecorder(QThread):
    """Record device screen via scrcpy --record to a single gameplay.mp4.

    Signals:
        recording_started():            Emitted once scrcpy process is alive.
        recording_finished(object):     Emitted with Path to completed mp4 on success.
        recording_error(str):           Emitted on any unrecoverable error.
    """

    recording_started = Signal()
    recording_finished = Signal(object)  # Path
    recording_error = Signal(str)
    validation_warning = Signal(str)  # emitted when mp4 moov atom is missing

    def __init__(
        self,
        serial: str,
        output_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._serial = serial
        self._output_path = output_path
        self._aborted: bool = False
        self._validation_warning: str | None = None

    # ── Graceful shutdown ────────────────────────────────────────────────────

    def _graceful_stop(self, proc: subprocess.Popen) -> None:
        """Send the platform-appropriate stop signal, then wait for graceful exit.

        On Windows: CTRL_BREAK_EVENT (lets scrcpy flush the mp4 muxer / moov atom).
        On macOS/Linux: SIGTERM via proc.terminate().

        After sending the signal, waits up to _TERMINATE_TIMEOUT_S seconds.
        If the process does not exit in time: hard-kills and sets _aborted=True
        to signal downstream validation that the recording may be corrupt.
        """
        if sys.platform == "win32":
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()

        try:
            proc.wait(timeout=_TERMINATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            logger.warning(
                "ScrcpyRecorder: scrcpy did not exit within %ds"
                " — force-killed; mp4 may be incomplete",
                _TERMINATE_TIMEOUT_S,
            )
            proc.kill()
            self._aborted = True

    # ── QThread entry point ──────────────────────────────────────────────────

    def run(self) -> None:
        """Main recording loop — runs in the worker thread."""
        logger.info(
            "ScrcpyRecorder: starting, serial=%s output=%s",
            self._serial,
            self._output_path,
        )
        try:
            proc = _spawn_scrcpy(self._serial, self._output_path)
            logger.info("ScrcpyRecorder: scrcpy proc started PID=%s", proc.pid)

            self.recording_started.emit()

            # Polling loop: check for interruption every 1 second
            while proc.poll() is None:
                if self.isInterruptionRequested():
                    logger.info("ScrcpyRecorder: interruption requested — terminating scrcpy")
                    self._graceful_stop(proc)
                    break
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    continue  # poll loop again

            logger.info(
                "ScrcpyRecorder: proc exited, returncode=%s",
                proc.returncode,
            )

            # Validate output file
            if not self._output_path.exists() or self._output_path.stat().st_size == 0:
                msg = (
                    f"Recording output missing or empty: {self._output_path}. "
                    "Check scrcpy binary and device connection."
                )
                logger.error("ScrcpyRecorder: %s", msg)
                self.recording_error.emit(msg)
                return

            logger.info(
                "ScrcpyRecorder: recording finished, output=%s size=%d bytes",
                self._output_path,
                self._output_path.stat().st_size,
            )

            # Validate mp4 for moov atom — warns user but never blocks packaging
            ok, reason = _validate_mp4(self._output_path)
            if ok:
                logger.info("ScrcpyRecorder: mp4 validation passed (moov atom present)")
            else:
                logger.warning(
                    "ScrcpyRecorder: mp4 validation failed: %s — file may be unplayable",
                    reason,
                )
                self._validation_warning = reason
                self.validation_warning.emit(reason)

            self.recording_finished.emit(self._output_path)

        except Exception as exc:
            logger.exception("ScrcpyRecorder: run() raised")
            self.recording_error.emit(str(exc))
