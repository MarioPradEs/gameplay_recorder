"""RED phase — Phase 13.1 + Phase 14c.1/14c.3: UI Threading / Worker Wiring tests.

Tests that MainWindow correctly creates, starts, and wires QThread workers
when the user clicks Record and Stop.

Spec references:
  - Requirement "GUI State Machine": IDLE → RECORDING → PACKAGING → DONE
  - Requirement "Segmented Video Capture": VideoSegmentRecorder worker lifecycle
  - Requirement "Periodic Screenshot Capture": ScreenshotCapture worker lifecycle
  - Phase 14c.1: Live session wiring (real AdbConnection, SessionMeta, session_dir)
  - Phase 14c.3: Error recovery — PACKAGING → IDLE on packaging failure
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gameplay_recorder.models.session import RecordingState, SessionMeta
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

    # Enable the record button (requires device serial + all form fields)
    window.idle_screen.set_device_status("emulator-5554")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
        ) as MockVSR,
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
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
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
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
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
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


# ---------------------------------------------------------------------------
# Phase 14c.1 — RED: Live session wiring
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_start_recording_passes_real_adb_connection_to_workers(qtbot):
    """Record click constructs AdbConnection(serial=...) and passes it to workers.

    Phase 14c.1: Workers MUST receive a real AdbConnection (not None).

    Verifies: VideoSegmentRecorder and ScreenshotCapture are both instantiated
    with adb_conn equal to the AdbConnection constructed from the device serial.
    """
    from gameplay_recorder.adb.connection import AdbConnection

    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("alice")

    mock_conn = MagicMock(spec=AdbConnection)

    with (
        patch(
            "gameplay_recorder.ui.main_window.AdbConnection",
            spec=AdbConnection,
        ) as MockConn,
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
        ) as MockVSR,
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ) as MockSC,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
    ):
        MockConn.return_value = mock_conn

        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # AdbConnection must be constructed with the device serial
        MockConn.assert_called_once_with("EMU-1")

        # Both workers receive the real AdbConnection instance (not None)
        vsr_call_kwargs = MockVSR.call_args
        sc_call_kwargs = MockSC.call_args
        assert vsr_call_kwargs is not None, "VideoSegmentRecorder was never called"
        assert sc_call_kwargs is not None, "ScreenshotCapture was never called"

        # Extract adb_conn kwarg or first positional
        vsr_kwargs = vsr_call_kwargs.kwargs
        sc_kwargs = sc_call_kwargs.kwargs
        assert vsr_kwargs.get("adb_conn") is mock_conn, (
            f"VideoSegmentRecorder adb_conn expected mock_conn, got {vsr_kwargs.get('adb_conn')!r}"
        )
        assert sc_kwargs.get("adb_conn") is mock_conn, (
            f"ScreenshotCapture adb_conn expected mock_conn, got {sc_kwargs.get('adb_conn')!r}"
        )


@pytest.mark.gui
def test_start_recording_builds_session_meta_from_form(qtbot):
    """Record click builds a SessionMeta from the form fields.

    Phase 14c.1: SessionMeta MUST have game_id, game_version, recorded_by,
    started_at (ISO8601 UTC), schema_version="1".

    Verifies: PackagingWorker eventually receives a SessionMeta with correct fields.
    We capture it by inspecting window._meta after start_recording_session.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    # Set up all form fields
    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.32.1")
    window.idle_screen.player_name_field.setText("alice")
    # game_dropdown defaults to zombie_gore

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
        patch("gameplay_recorder.ui.main_window.VideoSegmentRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
    ):
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

    # MainWindow must store _meta after start_recording_session
    assert hasattr(window, "_meta"), "MainWindow has no _meta attribute after start_recording"
    meta = window._meta
    assert isinstance(meta, SessionMeta), f"Expected SessionMeta, got {type(meta)}"
    assert meta.game_id == "zombie_gore"
    assert meta.game_version == "1.32.1"
    assert meta.recorded_by == "alice"
    assert meta.schema_version == "1"
    # started_at must be a valid ISO 8601 UTC string: YYYY-MM-DDTHH:MM:SSZ
    iso8601_utc = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    assert iso8601_utc.match(meta.started_at), (
        f"started_at {meta.started_at!r} does not match ISO8601 UTC pattern"
    )


@pytest.mark.gui
def test_start_recording_creates_session_dir(qtbot):
    """Record click creates a temporary session_dir under DEFAULT_OUTPUT_DIR.

    Phase 14c.1: A real session_dir MUST be created and passed to all three workers.

    Verifies: window._session_dir exists after start, and VideoSegmentRecorder +
    ScreenshotCapture both receive it.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
        ) as MockVSR,
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ) as MockSC,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
    ):
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

    # Session dir must be stored on the window
    assert hasattr(window, "_session_dir"), "MainWindow has no _session_dir after start"
    session_dir: Path = window._session_dir
    assert isinstance(session_dir, Path), f"Expected Path, got {type(session_dir)}"
    assert session_dir.exists(), f"session_dir {session_dir} was not created on disk"

    # Both capture workers receive the session_dir
    vsr_kwargs = MockVSR.call_args.kwargs
    sc_kwargs = MockSC.call_args.kwargs

    # VideoSegmentRecorder uses 'local_dir' param
    assert vsr_kwargs.get("local_dir") == session_dir, (
        f"VideoSegmentRecorder local_dir mismatch: {vsr_kwargs.get('local_dir')!r}"
    )
    # ScreenshotCapture uses 'session_dir' param
    assert sc_kwargs.get("session_dir") == session_dir, (
        f"ScreenshotCapture session_dir mismatch: {sc_kwargs.get('session_dir')!r}"
    )


@pytest.mark.gui
def test_stop_recording_passes_session_dir_and_meta_to_packaging_worker(qtbot):
    """Stop click passes real session_dir, meta, and output_dir to PackagingWorker.

    Phase 14c.1: PackagingWorker MUST NOT receive None for session_dir or meta.

    Verifies: PackagingWorker.__init__ is called with
      session_dir=<the temp dir from start_recording>
      meta=<the SessionMeta built from the form>
      output_dir=DEFAULT_OUTPUT_DIR
    """
    from gameplay_recorder.config import DEFAULT_OUTPUT_DIR

    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("2.0.0")
    window.idle_screen.player_name_field.setText("bob")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
        patch("gameplay_recorder.ui.main_window.VideoSegmentRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch(
            "gameplay_recorder.ui.main_window.PackagingWorker",
            spec=True,
        ) as MockPW,
    ):
        # Start recording
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )
        # Stop recording
        qtbot.mouseClick(
            window._recording_screen.stop_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # PackagingWorker must be called with real values
        MockPW.assert_called_once()
        pw_kwargs = MockPW.call_args.kwargs
        assert pw_kwargs.get("session_dir") is not None, "PackagingWorker session_dir is None"
        assert isinstance(pw_kwargs.get("session_dir"), Path), (
            f"session_dir should be Path, got {type(pw_kwargs.get('session_dir'))}"
        )
        assert pw_kwargs.get("meta") is not None, "PackagingWorker meta is None"
        assert isinstance(pw_kwargs.get("meta"), SessionMeta), (
            f"meta should be SessionMeta, got {type(pw_kwargs.get('meta'))}"
        )
        assert pw_kwargs.get("output_dir") == DEFAULT_OUTPUT_DIR, (
            f"output_dir expected {DEFAULT_OUTPUT_DIR}, got {pw_kwargs.get('output_dir')!r}"
        )


@pytest.mark.gui
def test_record_button_disabled_if_required_fields_empty(qtbot):
    """Record button stays disabled when version or player name is empty.

    Phase 14c.1: Form validation MUST prevent submission with empty required fields.

    Verifies:
    - Record button disabled when version_field is empty (device set)
    - Record button disabled when player_name_field is empty (device set)
    - Record button enabled only when device + version + player are all filled
    """
    window = MainWindow()
    qtbot.addWidget(window)

    # Device connected but fields empty → should be disabled
    window.idle_screen.set_device_status("EMU-1")
    assert not window.idle_screen.record_button.isEnabled(), (
        "Record button must be disabled when version is empty"
    )

    # Fill version but leave player empty → still disabled
    window.idle_screen.version_field.setText("1.0.0")
    assert not window.idle_screen.record_button.isEnabled(), (
        "Record button must be disabled when player name is empty"
    )

    # Fill player name → now all required fields filled → enabled
    window.idle_screen.player_name_field.setText("alice")
    assert window.idle_screen.record_button.isEnabled(), (
        "Record button must be enabled when device + version + player are all set"
    )

    # Clear version → disabled again
    window.idle_screen.version_field.clear()
    assert not window.idle_screen.record_button.isEnabled(), (
        "Record button must go back to disabled when version is cleared"
    )


# ---------------------------------------------------------------------------
# Phase 14c.3 — RED: PACKAGING → IDLE error recovery
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_packaging_failure_returns_to_idle_with_error_banner(qtbot):
    """PackagingWorker error signal transitions PACKAGING → IDLE with error banner.

    Phase 14c.3: When packaging fails, the app MUST NOT get stuck in PACKAGING.

    Verifies:
    - State transitions from PACKAGING → IDLE
    - IdleScreen shows an error banner with the failure message
    - Form is re-enabled after the error
    """
    window = MainWindow()
    qtbot.addWidget(window)

    # Drive to PACKAGING state
    window.start_recording.emit()
    window.stop_recording.emit()
    assert window.stacked.currentIndex() == RecordingState.PACKAGING.value

    # Simulate PackagingWorker emitting error
    error_message = "'NoneType' object has no attribute 'game_id'"
    window._on_packaging_error(error_message)

    # Must transition back to IDLE
    assert window.stacked.currentIndex() == RecordingState.IDLE.value, (
        f"Expected IDLE after packaging error, got state {window.stacked.currentIndex()}"
    )

    # IdleScreen must show an error banner
    assert hasattr(window.idle_screen, "error_banner"), (
        "IdleScreen must have an error_banner attribute"
    )
    assert window.idle_screen.error_banner.isVisible(), (
        "error_banner must be visible after packaging failure"
    )
    banner_text = window.idle_screen.error_banner.text()
    assert error_message in banner_text, (
        f"error_banner text must contain the error message. Got: {banner_text!r}"
    )

    # Form must be re-enabled (record button should be in its normal state,
    # not locked by RECORDING mode)
    assert window.idle_screen.game_dropdown.isEnabled(), (
        "game_dropdown must be re-enabled after returning to IDLE"
    )
