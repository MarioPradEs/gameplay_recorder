"""RED phase — Phase 14.1 + Phase 14d.1: App entrypoint tests.

Tests for create_app() and main() in gameplay_recorder.app.

Spec references:
  - Requirement "App Entrypoint": create_app returns QApplication instance.
  - Requirement "Auto-Update Check": update check fires without blocking IDLE state.
  - Phase 14d.1: main() configures logging via basicConfig at INFO level.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from gameplay_recorder.app import create_app
from gameplay_recorder.ui.main_window import MainWindow

# ---------------------------------------------------------------------------
# create_app() — returns QApplication
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_qapplication_created(qtbot):
    """create_app([]) returns a QApplication instance.

    Spec: Requirement "App Entrypoint" — create_app must return a QApplication.
    The function must reuse an existing QApplication if one is already running
    (pytest-qt already creates one, so this verifies the reuse path as well).
    """
    app = create_app([])

    assert isinstance(app, QApplication)


# ---------------------------------------------------------------------------
# MainWindow smoke — no exception on construction
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_main_window_shown_smoke(qtbot):
    """create_app([]) then MainWindow() — no exception, instance is MainWindow.

    Spec: Requirement "App Entrypoint" — main() constructs the MainWindow without
    crashing.  This test verifies the QApplication + MainWindow pair initialises
    successfully in the same process as the test suite.
    """
    create_app([])
    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(window, MainWindow)


# ---------------------------------------------------------------------------
# Phase 14d.1 — Logging configuration
# ---------------------------------------------------------------------------


def test_main_configures_logging():
    """main() calls logging.basicConfig with level=INFO before returning.

    Phase 14d.1: Without basicConfig, all loggers are silent (no stdout output).
    This test verifies that main() configures the root logger so that INFO+
    messages from any module (ScreenshotCapture, VideoSegmentRecorder, etc.)
    reach the console.

    Spec: Diagnostic requirement — logs must be visible during live runs.
    """
    from gameplay_recorder.app import main

    with (
        patch("logging.basicConfig") as mock_basicConfig,
        patch("gameplay_recorder.app.create_app"),
        patch("gameplay_recorder.app.MainWindow"),
        patch("gameplay_recorder.app.Thread"),
        patch("gameplay_recorder.app.discover_device", return_value=(None, "no device")),
    ):
        # Patch app.exec to avoid blocking the event loop
        import gameplay_recorder.app as app_module

        fake_app = app_module.create_app.return_value  # type: ignore[attr-defined]
        fake_app.exec.return_value = 0

        main()

    mock_basicConfig.assert_called_once()
    call_kwargs = mock_basicConfig.call_args
    # Must be called with level=logging.INFO (or lower, but INFO is the spec)
    level_arg = call_kwargs.kwargs.get("level") or (
        call_kwargs.args[0] if call_kwargs.args else None
    )
    assert level_arg == logging.INFO, (
        f"logging.basicConfig must be called with level=logging.INFO, got level={level_arg!r}"
    )
