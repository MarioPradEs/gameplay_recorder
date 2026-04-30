"""RED phase — Phase 13.1: UI Threading / Worker Wiring tests.

Tests that MainWindow correctly creates, starts, and wires QThread workers
when the user clicks Record and Stop.

Spec references:
  - Requirement "GUI State Machine": IDLE → RECORDING → PACKAGING → DONE
  - Requirement "Segmented Video Capture": VideoSegmentRecorder worker lifecycle
  - Requirement "Periodic Screenshot Capture": ScreenshotCapture worker lifecycle
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gameplay_recorder.models.session import RecordingState
from gameplay_recorder.ui.main_window import MainWindow

# ---------------------------------------------------------------------------
# Test 1: clicking Record button starts the VideoSegmentRecorder worker
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_record_button_click_starts_video_worker(qtbot):
    """Record button click creates and starts a VideoSegmentRecorder worker.

    Spec: Requirement "Segmented Video Capture" — worker MUST be started when
    recording begins.

    Verifies: MainWindow.start_recording_session() creates a
    VideoSegmentRecorder and calls .start() on it.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    # Enable the record button (requires a device serial)
    window.idle_screen.set_device_status("emulator-5554")

    with (
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
        ) as MockVSR,
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ),
    ):
        mock_vsr_instance = MockVSR.return_value

        # Click the record button
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        MockVSR.assert_called_once()
        mock_vsr_instance.start.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2: clicking Stop requests interruption on both workers
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_stop_button_click_stops_workers(qtbot):
    """Stop button click calls requestInterruption() on video + screenshot workers.

    Spec: Requirement "Segmented Video Capture" — workers MUST be interrupted
    gracefully when stop is requested.

    Verifies: MainWindow.stop_recording_session() calls requestInterruption()
    on both VideoSegmentRecorder and ScreenshotCapture instances.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("emulator-5554")

    with (
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
        ) as MockVSR,
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ) as MockSC,
        patch(
            "gameplay_recorder.ui.main_window.PackagingWorker",
            spec=True,
        ),
    ):
        mock_vsr_instance = MockVSR.return_value
        mock_sc_instance = MockSC.return_value

        # Start recording first
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # Now click stop
        qtbot.mouseClick(
            window._recording_screen.stop_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        mock_vsr_instance.requestInterruption.assert_called_once()
        mock_sc_instance.requestInterruption.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: Stop button click starts PackagingWorker
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_packaging_worker_started_after_stop(qtbot):
    """Stop button click creates and starts a PackagingWorker.

    Spec: Requirement "Segmented Video Capture" — after stopping, packaging
    MUST begin automatically.

    Verifies: MainWindow.stop_recording_session() creates a PackagingWorker
    and calls .start() on it.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("emulator-5554")

    with (
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
        ),
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ),
        patch(
            "gameplay_recorder.ui.main_window.PackagingWorker",
            spec=True,
        ) as MockPW,
    ):
        mock_pw_instance = MockPW.return_value

        # Start then stop
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )
        qtbot.mouseClick(
            window._recording_screen.stop_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        MockPW.assert_called_once()
        mock_pw_instance.start.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: PackagingWorker finished signal transitions state to DONE
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_packaging_finished_signal_transitions_to_done(qtbot):
    """PackagingWorker emitting finished(path) transitions MainWindow to DONE state.

    Spec: Requirement "GUI State Machine" — PACKAGING → DONE on packaging_finished.

    Verifies: _on_packaging_finished(path) sets the zip path on DoneScreen
    and transitions to DONE state.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    # Manually drive to PACKAGING state (bypassing worker creation)
    window.start_recording.emit()
    window.stop_recording.emit()
    assert window.stacked.currentIndex() == RecordingState.PACKAGING.value

    # Call the slot directly with a path
    zip_path = Path("/tmp/test_session.zip")
    window._on_packaging_finished(zip_path)

    assert window.stacked.currentIndex() == RecordingState.DONE.value
    assert "test_session.zip" in window._done_screen.zip_path_label.text()


# ---------------------------------------------------------------------------
# Test 5: recording_error signal shows error banner
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_recording_error_shows_banner(qtbot):
    """VideoSegmentRecorder emitting recording_error shows the error banner.

    Spec: Requirement "Segmented Video Capture" — recording errors MUST be
    surfaced to the user in the UI.

    Verifies: _on_recording_error(message) shows a visible error banner
    with the error message text.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    # Call the error slot directly
    window._on_recording_error("fail")

    assert window._recording_screen.error_banner.isVisible()
    assert "fail" in window._recording_screen.error_banner.text()
