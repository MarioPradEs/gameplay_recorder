"""RED phase — Phase 11.1: GUI State Machine tests.

Tests the QStackedWidget-based state machine in MainWindow.
State machine lives in main_window.py (coupled to Qt — requires qtbot / QApplication).
RecordingState enum is imported from models.session.

Invalid transition contract: silently blocked (no crash, state unchanged) — per spec
Requirement "GUI State Machine", Scenario "Invalid transition blocked".
"""

import pytest
from gameplay_recorder.ui.main_window import MainWindow

from gameplay_recorder.models.session import RecordingState


@pytest.mark.gui
def test_initial_state_is_idle(qtbot):
    """MainWindow starts in IDLE state (stacked index 0)."""
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.stacked.currentIndex() == RecordingState.IDLE.value


@pytest.mark.gui
def test_transition_idle_to_recording(qtbot):
    """Emitting start_recording from IDLE transitions to RECORDING and locks form inputs."""
    window = MainWindow()
    qtbot.addWidget(window)

    window.start_recording.emit()

    assert window.stacked.currentIndex() == RecordingState.RECORDING.value
    # Spec: Requirement "GUI State Machine", Scenario "Form locked during recording"
    # All form inputs on the idle screen must be disabled.
    assert not window.idle_screen.game_dropdown.isEnabled()
    assert not window.idle_screen.player_name_field.isEnabled()


@pytest.mark.gui
def test_transition_recording_to_packaging(qtbot):
    """Emitting stop_recording from RECORDING transitions to PACKAGING."""
    window = MainWindow()
    qtbot.addWidget(window)

    # Move to RECORDING first
    window.start_recording.emit()
    assert window.stacked.currentIndex() == RecordingState.RECORDING.value

    window.stop_recording.emit()

    assert window.stacked.currentIndex() == RecordingState.PACKAGING.value


@pytest.mark.gui
def test_transition_packaging_to_done(qtbot):
    """Emitting packaging_finished from PACKAGING transitions to DONE."""
    window = MainWindow()
    qtbot.addWidget(window)

    # Drive through IDLE → RECORDING → PACKAGING
    window.start_recording.emit()
    window.stop_recording.emit()
    assert window.stacked.currentIndex() == RecordingState.PACKAGING.value

    window.packaging_finished.emit()

    assert window.stacked.currentIndex() == RecordingState.DONE.value


@pytest.mark.gui
def test_transition_done_to_idle(qtbot):
    """Emitting record_again from DONE transitions back to IDLE."""
    window = MainWindow()
    qtbot.addWidget(window)

    # Drive through full cycle to DONE
    window.start_recording.emit()
    window.stop_recording.emit()
    window.packaging_finished.emit()
    assert window.stacked.currentIndex() == RecordingState.DONE.value

    window.record_again.emit()

    assert window.stacked.currentIndex() == RecordingState.IDLE.value


@pytest.mark.gui
def test_invalid_transition_stop_from_idle_is_blocked(qtbot):
    """Emitting stop_recording while in IDLE state is silently blocked.

    Spec: Requirement "GUI State Machine", Scenario "Invalid transition blocked".
    The app remains in IDLE and does not crash.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.stacked.currentIndex() == RecordingState.IDLE.value

    # This must NOT crash and must NOT change state
    window.stop_recording.emit()

    assert window.stacked.currentIndex() == RecordingState.IDLE.value
