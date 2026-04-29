"""Periodic screenshot capture for gameplay_recorder.

Captures device screenshots via adb screencap at a configurable interval
(default: 5 s) during a recording session. Screenshots are saved as
screenshots/NNNN.png (zero-padded 4-digit index) under the session directory.

Design: capture/screenshot_capture.py — ScreenshotCapture(QThread)
Signal: screenshot_saved(Path)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from gameplay_recorder.config import SCREENSHOT_INTERVAL_S

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
# Pure helpers
# ---------------------------------------------------------------------------

_SCREENSHOTS_SUBDIR = "screenshots"


def screenshot_filename(index: int) -> str:
    """Return the zero-padded filename for screenshot *index*.

    Examples:
        screenshot_filename(0)    -> '0000.png'
        screenshot_filename(42)   -> '0042.png'
        screenshot_filename(9999) -> '9999.png'
    """
    return f"{index:04d}.png"


def screenshot_path(index: int, session_dir: Path) -> Path:
    """Return the full host path for screenshot *index* inside *session_dir*.

    The screenshots live in a ``screenshots/`` sub-directory so that the
    ZIP packager can include them as ``screenshots/NNNN.png``.

    Examples:
        screenshot_path(0, Path('/tmp/session'))
        -> Path('/tmp/session/screenshots/0000.png')
    """
    return session_dir / _SCREENSHOTS_SUBDIR / screenshot_filename(index)


# ---------------------------------------------------------------------------
# ScreenshotCapture — QThread worker
# ---------------------------------------------------------------------------


class ScreenshotCapture(QThread):
    """Capture periodic screenshots during a recording session.

    Runs in a worker thread. Every *interval_s* seconds it calls
    ``adb_conn.screencap()`` and writes raw PNG bytes to
    ``session_dir/screenshots/NNNN.png``.

    Signals:
        screenshot_saved(Path): Emitted after each screenshot is written.
    """

    screenshot_saved = Signal(object)  # Path

    def __init__(
        self,
        adb_conn: AdbConnection,
        session_dir: Path,
        interval_s: int = SCREENSHOT_INTERVAL_S,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._adb_conn = adb_conn
        self._session_dir = session_dir
        self.interval_s = interval_s
        self._screenshot_count: int = 0

    # ── Public helper (also called by _take_screenshot for testability) ───────

    def _take_screenshot(self) -> Path:
        """Capture one screenshot and write it to disk.

        Returns the path of the written file.
        Increments the internal counter.
        """
        dest = screenshot_path(self._screenshot_count, self._session_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)

        png_bytes = self._adb_conn.screencap()

        with open(dest, "wb") as fh:
            fh.write(png_bytes)

        self._screenshot_count += 1
        self.screenshot_saved.emit(dest)
        return dest

    # ── QThread entry point ──────────────────────────────────────────────────

    def run(self) -> None:
        """Main capture loop — runs in the worker thread."""
        while not self.isInterruptionRequested():
            try:
                self._take_screenshot()
            except Exception:
                pass  # silently skip failed captures — recording must continue
            # Sleep in small increments so interruption is responsive
            elapsed = 0.0
            while elapsed < self.interval_s and not self.isInterruptionRequested():
                time.sleep(0.1)
                elapsed += 0.1

    @property
    def screenshots(self) -> list[Path]:
        """Return paths of all screenshots captured so far."""
        return [screenshot_path(i, self._session_dir) for i in range(self._screenshot_count)]
