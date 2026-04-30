"""Main application window with QStackedWidget-based state machine.

Spec: Requirement "GUI State Machine" — 4 states: IDLE → RECORDING → PACKAGING → DONE.

Transition table (valid only):
    IDLE        + start_recording   → RECORDING
    RECORDING   + stop_recording    → PACKAGING
    PACKAGING   + packaging_finished → DONE
    DONE        + record_again      → IDLE

Invalid transitions are silently blocked — state unchanged, no exception.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from gameplay_recorder.models.session import RecordingState

# ---------------------------------------------------------------------------
# Screen widgets (stubs — full implementation in Phase 12)
# ---------------------------------------------------------------------------


class IdleScreen(QWidget):
    """Idle state screen — game form and Record button.

    Exposes:
        game_dropdown (QComboBox): game selector; disabled during RECORDING.
        player_name_field (QLineEdit): player name input; disabled during RECORDING.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.game_dropdown = QComboBox(self)
        self.game_dropdown.addItem("zombie_gore")
        self.player_name_field = QLineEdit(self)


class RecordingScreen(QWidget):
    """Recording state screen — timer, segment counter, Stop button (Phase 12 stub)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel("Recording…", self)


class PackagingScreen(QWidget):
    """Packaging state screen — progress indicator (Phase 12 stub)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel("Packaging…", self)


class DoneScreen(QWidget):
    """Done state screen — ZIP path, Open Folder, Record Again (Phase 12 stub)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel("Done.", self)


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

#: Maps (current_state, signal_name) → next_state for VALID transitions only.
_TRANSITIONS: dict[tuple[RecordingState, str], RecordingState] = {
    (RecordingState.IDLE, "start_recording"): RecordingState.RECORDING,
    (RecordingState.RECORDING, "stop_recording"): RecordingState.PACKAGING,
    (RecordingState.PACKAGING, "packaging_finished"): RecordingState.DONE,
    (RecordingState.DONE, "record_again"): RecordingState.IDLE,
}


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """Top-level application window.

    Owns the QStackedWidget and drives all state transitions via signals.
    Each signal corresponds to one valid arc in the state machine; invalid
    emissions are silently blocked (spec: "Invalid transitions MUST be
    silently blocked (no crash)").

    Signals:
        start_recording: IDLE → RECORDING
        stop_recording:  RECORDING → PACKAGING
        packaging_finished: PACKAGING → DONE
        record_again:    DONE → IDLE

    Attributes:
        stacked (QStackedWidget): pages indexed by RecordingState integer values.
        idle_screen (IdleScreen): page 0 — exposes ``game_dropdown`` and
            ``player_name_field`` (disabled while in RECORDING state).
    """

    start_recording: Signal = Signal()
    stop_recording: Signal = Signal()
    packaging_finished: Signal = Signal()
    record_again: Signal = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gameplay Recorder")

        # Build screens in the same order as RecordingState integer values.
        self.idle_screen = IdleScreen()
        self._recording_screen = RecordingScreen()
        self._packaging_screen = PackagingScreen()
        self._done_screen = DoneScreen()

        self.stacked = QStackedWidget()
        self.stacked.insertWidget(RecordingState.IDLE, self.idle_screen)
        self.stacked.insertWidget(RecordingState.RECORDING, self._recording_screen)
        self.stacked.insertWidget(RecordingState.PACKAGING, self._packaging_screen)
        self.stacked.insertWidget(RecordingState.DONE, self._done_screen)

        self.setCentralWidget(self.stacked)

        # Connect signals to the generic transition dispatcher.
        self.start_recording.connect(lambda: self._transition("start_recording"))
        self.stop_recording.connect(lambda: self._transition("stop_recording"))
        self.packaging_finished.connect(lambda: self._transition("packaging_finished"))
        self.record_again.connect(lambda: self._transition("record_again"))

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition(self, trigger: str) -> None:
        """Attempt a state transition for *trigger*.

        If the ``(current_state, trigger)`` pair is not in the transition
        table the call is silently ignored — state and UI remain unchanged.
        """
        current = RecordingState(self.stacked.currentIndex())
        next_state = _TRANSITIONS.get((current, trigger))
        if next_state is None:
            # Invalid transition — spec: "silently blocked (no crash)".
            return
        self._apply_state(next_state)

    def _apply_state(self, state: RecordingState) -> None:
        """Switch QStackedWidget to *state* and apply side-effects."""
        self.stacked.setCurrentIndex(state)

        # Spec: "Form locked during recording" — all form inputs disabled
        # while in RECORDING; re-enabled for every other state.
        form_enabled = state != RecordingState.RECORDING
        self.idle_screen.game_dropdown.setEnabled(form_enabled)
        self.idle_screen.player_name_field.setEnabled(form_enabled)
