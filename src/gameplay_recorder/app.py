"""Application entry point for gameplay_recorder.

Provides two public functions:
- create_app(argv)  — create or reuse the QApplication singleton.
- main()            — wire config, create MainWindow, fire-and-forget update
                      check, discover ADB device, show window, run event loop.

Design: Phase 14 — App Entrypoint.
Phase 14b — ADB device discovery wired into main().
"""

from __future__ import annotations

import logging
import sys
from threading import Thread

from PySide6.QtWidgets import QApplication

from gameplay_recorder import __version__
from gameplay_recorder.adb.connection import discover_device
from gameplay_recorder.capture.event_monitor import detect_touch_device
from gameplay_recorder.ui.main_window import MainWindow
from gameplay_recorder.update.checker import check_for_update

logger = logging.getLogger(__name__)


def create_app(argv: list[str]) -> QApplication:
    """Create and return the QApplication, reusing an existing instance if present.

    Args:
        argv: Command-line arguments forwarded to QApplication constructor.
              Pass ``[]`` to suppress argument forwarding.

    Returns:
        The running QApplication instance (new or pre-existing).

    This function is idempotent: calling it multiple times (e.g. in tests that
    share a process) returns the same QApplication without creating a second one.
    """
    existing = QApplication.instance()
    if existing is not None:
        return existing  # type: ignore[return-value]
    return QApplication(argv)


def main() -> int:
    """Application entry point.

    Creates the QApplication, constructs MainWindow, fires an asynchronous
    update check (fire-and-forget — must NOT block the IDLE state), shows the
    window, and starts the Qt event loop.

    Returns:
        Exit code from ``app.exec()`` — callers should pass this to
        ``sys.exit()`` if desired.  ``main()`` itself never calls
        ``sys.exit()``.

    Spec: Requirement "Auto-Update Check" — the check is fire-and-forget;
    network failures are silently swallowed.
    Phase 14d.1: Configures root logger so all module loggers write to stdout.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = create_app(sys.argv)

    window = MainWindow()

    # Fire-and-forget update check — runs in a daemon thread so it never
    # blocks the event loop or the IDLE state.  If a newer version is found,
    # ``set_update_available`` is called on the idle_screen banner.
    # All exceptions are swallowed (spec: "Network unavailable scenario").
    def _check_update() -> None:
        try:
            newer = check_for_update(__version__)
            if newer is not None:
                window.idle_screen.set_update_available(newer)
        except Exception:  # noqa: BLE001
            pass

    _update_thread = Thread(target=_check_update, daemon=True)
    _update_thread.start()

    # Discover ADB device before showing the window so the Record button
    # state is correct on first render.
    # discover_device() never raises — it returns (None, error) on failure.
    try:
        serial, _error = discover_device()
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error from discover_device()")
        serial = None

    window.idle_screen.set_device_status(serial)

    # Detect the touchscreen input device on the phone so the IdleScreen knows
    # whether to enable Record directly, or to surface the escape-hatch UI.
    # detect_touch_device() runs `adb shell getevent -lp` and may fail if the
    # device disappears or adb errors out — swallow and treat as "no touch".
    if serial is not None:
        try:
            touch_device = detect_touch_device(serial)
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error from detect_touch_device()")
            touch_device = None
    else:
        touch_device = None

    window.idle_screen.set_touch_device(touch_device)

    window.show()
    return app.exec()
