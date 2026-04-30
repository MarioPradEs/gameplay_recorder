"""RED phase — Phase 14.1: App entrypoint tests.

Tests for create_app() and main() in gameplay_recorder.app.

Spec references:
  - Requirement "App Entrypoint": create_app returns QApplication instance.
  - Requirement "Auto-Update Check": update check fires without blocking IDLE state.
"""

from __future__ import annotations

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
