"""scrcpy-based video recorder for gameplay_recorder.

Records the device screen on the HOST using scrcpy v3.3.4.
Produces a single gameplay.mp4 file — no segmentation, no /sdcard access.

Design: capture/scrcpy_recorder.py — ScrcpyRecorder(QThread)
Signals: recording_started(), recording_finished(object), recording_error(str)
"""

from __future__ import annotations

import logging
import shutil
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


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


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
    ]
    logger.info(
        "ScrcpyRecorder: spawning scrcpy serial=%s output=%s",
        serial,
        output_path,
    )
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def check_host_free_space(output_dir: Path, min_gb: float = 1) -> str | None:
    """Check available storage on the host output directory.

    Returns:
        None — if free space is >= min_gb (recording can proceed).
        str  — human-readable error message if space is < min_gb.

    Spec: Requirement 'Free-Space Pre-Check' (Modified) — host disk, 1 GB threshold.

    Note: This stub is intentionally minimal for Phase 3.
    Full implementation arrives in Phase 4.
    """
    # Phase 3 stub — always returns None (OK).
    # Phase 4 fills in real shutil.disk_usage logic.
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

    def __init__(
        self,
        serial: str,
        output_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._serial = serial
        self._output_path = output_path

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
                    proc.terminate()
                    try:
                        proc.wait(timeout=_TERMINATE_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        logger.warning(
                            "ScrcpyRecorder: scrcpy did not terminate within %ds"
                            " — force-killed; mp4 may be incomplete",
                            _TERMINATE_TIMEOUT_S,
                        )
                        proc.kill()
                        proc.wait()
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
            self.recording_finished.emit(self._output_path)

        except Exception as exc:
            logger.exception("ScrcpyRecorder: run() raised")
            self.recording_error.emit(str(exc))
