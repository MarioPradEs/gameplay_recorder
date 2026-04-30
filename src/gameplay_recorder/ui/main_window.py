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

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from gameplay_recorder.adb.connection import AdbConnection
from gameplay_recorder.capture.screenshot_capture import ScreenshotCapture
from gameplay_recorder.capture.video_recorder import VideoSegmentRecorder
from gameplay_recorder.config import DEFAULT_OUTPUT_DIR, SCREENSHOT_INTERVAL_S, SEGMENT_DURATION_S
from gameplay_recorder.models.session import RecordingState, SessionMeta
from gameplay_recorder.packaging.worker import PackagingWorker
from gameplay_recorder.ui.done_screen import DoneScreen
from gameplay_recorder.ui.idle_screen import IdleScreen
from gameplay_recorder.ui.packaging_screen import PackagingScreen
from gameplay_recorder.ui.recording_screen import RecordingScreen

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-export screen widgets so existing imports of the form
# ``from gameplay_recorder.ui.main_window import IdleScreen`` continue to work.
# ---------------------------------------------------------------------------

__all__ = [
    "DoneScreen",
    "IdleScreen",
    "MainWindow",
    "PackagingScreen",
    "RecordingScreen",
]

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

        # Wire Record / Stop buttons to worker-management slots.
        self.idle_screen.record_button.clicked.connect(self.start_recording_session)
        self._recording_screen.stop_button.clicked.connect(self.stop_recording_session)

        # Worker handles (None when no recording is active).
        self._video_worker: VideoSegmentRecorder | None = None
        self._screenshot_worker: ScreenshotCapture | None = None
        self._packaging_worker: PackagingWorker | None = None

        # Session state (populated by start_recording_session, used by stop).
        self._adb_conn: AdbConnection | None = None
        self._session_dir: Path | None = None
        self._meta: SessionMeta | None = None
        self._start_time: float | None = None

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

    # ------------------------------------------------------------------
    # Worker management slots
    # ------------------------------------------------------------------

    def start_recording_session(self) -> None:
        """Create and start video + screenshot workers, then transition IDLE → RECORDING.

        Spec: Requirement "Segmented Video Capture" — worker lifecycle.
        Phase 14c: Wires real AdbConnection, SessionMeta, and session_dir.

        Guards:
        - Serial must be set on IdleScreen (device connected).
        - version_field and player_name_field must be non-empty.
        If any guard fails, logs a warning and stays in IDLE.
        """
        # ── Guard: device serial ──────────────────────────────────────────
        serial = self.idle_screen._current_serial
        if not serial:
            logger.warning("start_recording_session: no device serial — staying in IDLE")
            return

        # ── Guard: required form fields ───────────────────────────────────
        game_version = self.idle_screen.version_field.text().strip()
        recorded_by = self.idle_screen.player_name_field.text().strip()
        if not game_version or not recorded_by:
            logger.warning("start_recording_session: version/player empty — staying in IDLE")
            self.idle_screen.show_error_banner("Please fill version and player name")
            return

        # ── Build live AdbConnection ──────────────────────────────────────
        self._adb_conn = AdbConnection(serial)

        # ── Build SessionMeta ─────────────────────────────────────────────
        self._start_time = time.time()
        started_at = datetime.fromtimestamp(self._start_time, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self._meta = SessionMeta(
            game_id=self.idle_screen.selected_game_id(),
            game_version=game_version,
            recorded_by=recorded_by,
            started_at=started_at,
            duration_seconds=0,
            schema_version="1",
        )

        # ── Create session directory ──────────────────────────────────────
        session_dir = DEFAULT_OUTPUT_DIR / f".tmp_{int(self._start_time)}"
        session_dir.mkdir(parents=True, exist_ok=True)
        self._session_dir = session_dir

        # ── Create workers with real args ─────────────────────────────────
        self._video_worker = VideoSegmentRecorder(
            adb_conn=self._adb_conn,
            local_dir=self._session_dir,
            duration=SEGMENT_DURATION_S,
        )
        self._screenshot_worker = ScreenshotCapture(
            adb_conn=self._adb_conn,
            session_dir=self._session_dir,
            interval_s=SCREENSHOT_INTERVAL_S,
        )

        # Wire error signal before starting.
        self._video_worker.recording_error.connect(self._on_recording_error)

        self._video_worker.start()
        self._screenshot_worker.start()

        # Transition IDLE → RECORDING.
        self.start_recording.emit()

    def stop_recording_session(self) -> None:
        """Interrupt workers, start packaging, then transition RECORDING → PACKAGING.

        Spec: Requirement "Segmented Video Capture" — graceful stop.
        Phase 14c: Uses real session_dir and meta stored during start_recording_session.
        """
        if self._video_worker is not None:
            self._video_worker.requestInterruption()
        if self._screenshot_worker is not None:
            self._screenshot_worker.requestInterruption()

        # Update duration now that the session is ending.
        if self._meta is not None and self._start_time is not None:
            elapsed = int(time.time() - self._start_time)
            # SessionMeta is frozen — rebuild with updated duration_seconds.
            self._meta = SessionMeta(
                game_id=self._meta.game_id,
                game_version=self._meta.game_version,
                recorded_by=self._meta.recorded_by,
                started_at=self._meta.started_at,
                duration_seconds=elapsed,
                schema_version=self._meta.schema_version,
            )

        # Create and start PackagingWorker with real args.
        segments = list(self._video_worker.segments) if self._video_worker is not None else []
        self._packaging_worker = PackagingWorker(
            segments=segments,
            session_dir=self._session_dir or Path("."),
            meta=self._meta,  # type: ignore[arg-type]
            output_dir=DEFAULT_OUTPUT_DIR,
        )
        self._packaging_worker.finished.connect(self._on_packaging_finished)
        self._packaging_worker.error.connect(self._on_packaging_error)

        self._packaging_worker.start()

        # Transition RECORDING → PACKAGING.
        self.stop_recording.emit()

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------

    def _on_packaging_finished(self, path: Path) -> None:
        """Handle packaging completion — set ZIP path on DoneScreen and go DONE.

        Args:
            path: Path to the produced ZIP file.

        Spec: Requirement "GUI State Machine" — PACKAGING → DONE.
        """
        self._done_screen.set_zip_path(path)
        self.packaging_finished.emit()

    def _on_recording_error(self, message: str) -> None:
        """Display a recording error banner on the RecordingScreen.

        Args:
            message: Human-readable error description from VideoSegmentRecorder.

        Spec: Requirement "Segmented Video Capture" — errors surface to the user.
        """
        self._recording_screen.error_banner.setText(message)
        self._recording_screen.error_banner.setVisible(True)

    def _on_packaging_error(self, message: str) -> None:
        """Handle a PackagingWorker error — transition PACKAGING → IDLE with error banner.

        Args:
            message: Human-readable failure description from PackagingWorker.

        Phase 14c: Prevents the app from getting stuck in PACKAGING state on failure.
        """
        logger.error("PackagingWorker failed: %s", message)
        # Transition back to IDLE via the state machine.
        self.stacked.setCurrentIndex(RecordingState.IDLE)
        # Re-enable form inputs (they're locked during RECORDING but IDLE allows them).
        self._apply_state(RecordingState.IDLE)
        # Show error banner on IdleScreen so the user knows what went wrong.
        self.idle_screen.show_error_banner(message)
