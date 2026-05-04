"""RED phase — Phase 13.1 + 14c.1/14c.3 + 14d.2/14d.3/14d.5: UI Threading / Worker Wiring tests.

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
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gameplay_recorder.models.session import RecordingState, SessionMeta
from gameplay_recorder.ui.main_window import MainWindow

# ---------------------------------------------------------------------------
# Test 1: clicking Record button starts the VideoSegmentRecorder worker
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
)
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


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
)
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


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
)
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
    """Record click calls AdbConnection.select_single_device() and passes the
    resulting connected instance to ScreenshotCapture and TouchEventMonitor.

    Phase 14c.1 (updated by 14c-fix + Phase 5): AdbConnection MUST be fully-wired
    before workers are started. Scope: ScreenshotCapture + TouchEventMonitor
    (ScrcpyRecorder does NOT receive adb_conn — it takes serial + output_path).

    Verifies: AdbConnection.select_single_device() is called, and ScreenshotCapture
    receives adb_conn equal to the instance returned by select_single_device().
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
            "gameplay_recorder.ui.main_window.ScrcpyRecorder",
            spec=True,
        ),
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ) as MockSC,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.check_host_free_space", return_value=None),
    ):
        MockConn.select_single_device.return_value = mock_conn

        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # AdbConnection.select_single_device() must be called (fully-wired path)
        MockConn.select_single_device.assert_called_once()

        # ScreenshotCapture receives the real AdbConnection instance
        sc_call_kwargs = MockSC.call_args
        assert sc_call_kwargs is not None, "ScreenshotCapture was never called"

        sc_kwargs = sc_call_kwargs.kwargs
        assert sc_kwargs.get("adb_conn") is mock_conn, (
            f"ScreenshotCapture adb_conn expected mock_conn, got {sc_kwargs.get('adb_conn')!r}"
        )


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
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


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
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


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
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


# ---------------------------------------------------------------------------
# Phase 14c-fix.1 — RED: AdbConnection.select_single_device() called before workers
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
)
@pytest.mark.gui
def test_start_recording_connects_adb_before_passing_to_workers(qtbot):
    """start_recording_session() MUST call AdbConnection.select_single_device() and
    pass the resulting connected instance to workers; workers MUST NOT be created
    if select_single_device() raises.

    Phase 14c-fix: AdbConnection(serial) leaves _adb_device=None. Workers call
    screencap()/shell() which call _ensure_device() → AdbCommandError. The fix:
    replace AdbConnection(serial) with AdbConnection.select_single_device() so
    _adb_device is set before the workers are instantiated.

    Verifies (happy path):
    1. AdbConnection.select_single_device() is called (not just AdbConnection(serial)).
    2. The connected instance returned by select_single_device() is what is passed
       to VideoSegmentRecorder and ScreenshotCapture as adb_conn.
    3. Workers are instantiated AFTER select_single_device() returns (i.e. connection
       precedes worker creation).

    Verifies (error path):
    4. If select_single_device() raises any exception, VideoSegmentRecorder and
       ScreenshotCapture are NOT instantiated.
    5. The window stays in IDLE state after the connection failure.
    6. idle_screen.show_error_banner() is called with a message containing
       "ADB connection failed".
    """
    from gameplay_recorder.adb.connection import AdbConnection, NoDeviceConnectedError

    # ── Happy path ─────────────────────────────────────────────────────────────
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    mock_conn = MagicMock(spec=AdbConnection)
    call_order: list[str] = []

    def _track_select(*args, **kwargs):
        call_order.append("select_single_device")
        return mock_conn

    def _track_vsr(*args, **kwargs):
        call_order.append("VideoSegmentRecorder")
        return MagicMock()

    def _track_sc(*args, **kwargs):
        call_order.append("ScreenshotCapture")
        return MagicMock()

    with (
        patch(
            "gameplay_recorder.ui.main_window.AdbConnection",
        ) as MockAdbConn,
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
            side_effect=_track_vsr,
        ) as MockVSR,
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
            side_effect=_track_sc,
        ) as MockSC,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
    ):
        MockAdbConn.select_single_device.side_effect = _track_select

        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # 1. select_single_device must have been called
        MockAdbConn.select_single_device.assert_called_once()

        # 2. Workers receive the connected instance from select_single_device
        vsr_kwargs = MockVSR.call_args.kwargs
        sc_kwargs = MockSC.call_args.kwargs
        assert vsr_kwargs.get("adb_conn") is mock_conn, (
            f"VideoSegmentRecorder.adb_conn must be the connected instance, "
            f"got {vsr_kwargs.get('adb_conn')!r}"
        )
        assert sc_kwargs.get("adb_conn") is mock_conn, (
            f"ScreenshotCapture.adb_conn must be the connected instance, "
            f"got {sc_kwargs.get('adb_conn')!r}"
        )

        # 3. Connection must precede both worker instantiations
        assert call_order.index("select_single_device") < call_order.index(
            "VideoSegmentRecorder"
        ), "select_single_device() must be called BEFORE VideoSegmentRecorder()"
        assert call_order.index("select_single_device") < call_order.index("ScreenshotCapture"), (
            "select_single_device() must be called BEFORE ScreenshotCapture()"
        )

    # ── Error path ─────────────────────────────────────────────────────────────
    window2 = MainWindow()
    qtbot.addWidget(window2)

    window2.idle_screen.set_device_status("EMU-1")
    window2.idle_screen.version_field.setText("1.0.0")
    window2.idle_screen.player_name_field.setText("tester")

    with (
        patch(
            "gameplay_recorder.ui.main_window.AdbConnection",
        ) as MockAdbConn2,
        patch(
            "gameplay_recorder.ui.main_window.VideoSegmentRecorder",
            spec=True,
        ) as MockVSR2,
        patch(
            "gameplay_recorder.ui.main_window.ScreenshotCapture",
            spec=True,
        ) as MockSC2,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
    ):
        MockAdbConn2.select_single_device.side_effect = NoDeviceConnectedError(
            "No ADB device detected."
        )

        qtbot.mouseClick(
            window2.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # 4. Workers must NOT be created if connection fails
        MockVSR2.assert_not_called()
        MockSC2.assert_not_called()

        # 5. Window stays in IDLE
        assert window2.stacked.currentIndex() == RecordingState.IDLE.value, (
            f"Expected IDLE after ADB connect failure, got state {window2.stacked.currentIndex()}"
        )

        # 6. Error banner shows "ADB connection failed"
        assert window2.idle_screen.error_banner.isVisible(), (
            "error_banner must be visible after ADB connect failure"
        )
        assert "ADB connection failed" in window2.idle_screen.error_banner.text(), (
            f"error_banner must say 'ADB connection failed', "
            f"got: {window2.idle_screen.error_banner.text()!r}"
        )


# ---------------------------------------------------------------------------
# Phase 14d.2 — RED: TouchEventMonitor must be spawned in start_recording_session
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
)
@pytest.mark.gui
def test_start_recording_spawns_touch_event_monitor(qtbot):
    """start_recording_session() MUST instantiate and start a TouchEventMonitor.

    Phase 14d.2: Spec Requirement "Raw Touch Event Capture" — events.jsonl is
    never created because TouchEventMonitor is never started.

    Verifies:
    1. TouchEventMonitor is instantiated with adb=<the live AdbConnection>,
       stop_event=<a threading.Event>.
    2. TouchEventMonitor.start() is called.
    3. On stop_recording_session(), stop_event.set() is called (or .stop() on monitor).
    """
    import threading

    from gameplay_recorder.adb.connection import AdbConnection

    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    mock_conn = MagicMock(spec=AdbConnection)
    mock_monitor = MagicMock()

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection") as MockAdbConn,
        patch("gameplay_recorder.ui.main_window.VideoSegmentRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch(
            "gameplay_recorder.ui.main_window.TouchEventMonitor",
            return_value=mock_monitor,
        ) as MockTEM,
    ):
        MockAdbConn.select_single_device.return_value = mock_conn

        # Click Record
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # 1. TouchEventMonitor must be instantiated
        MockTEM.assert_called_once()
        call_kwargs = MockTEM.call_args.kwargs
        # adb must be the live connection
        assert call_kwargs.get("adb") is mock_conn, (
            f"TouchEventMonitor 'adb' must be the live AdbConnection, "
            f"got {call_kwargs.get('adb')!r}"
        )
        # stop_event must be a threading.Event
        stop_event = call_kwargs.get("stop_event")
        assert isinstance(stop_event, threading.Event), (
            f"TouchEventMonitor 'stop_event' must be threading.Event, got {type(stop_event)!r}"
        )

        # 2. .start() must have been called
        mock_monitor.start.assert_called_once()

        # 3. On stop, the stop_event must be set
        qtbot.mouseClick(
            window._recording_screen.stop_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # stop_event.set() stops the monitor thread
        assert stop_event.is_set(), "stop_event must be set() when stop_recording_session() runs"


# ---------------------------------------------------------------------------
# Phase 14d.3 — RED: RecordingScreen timer ticks every second
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Phase 6 cleanup: pre-pivot test patches removed VideoSegmentRecorder; "
    "to be deleted/migrated in Batch 4."
)
@pytest.mark.gui
def test_recording_screen_timer_ticks_every_second(qtbot):
    """After start_recording_session(), the timer_label must advance after ~2 seconds.

    Phase 14d.3: A QTimer(1000ms) must be started in start_recording_session()
    and connected to update_elapsed() on RecordingScreen.

    Verifies:
    - timer_label starts at "0:00"
    - After waiting 2.5s (using qtbot.wait to keep event loop alive), it shows
      a non-zero elapsed time (at least "0:01" or higher).
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection"),
        patch("gameplay_recorder.ui.main_window.VideoSegmentRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor"),
    ):
        # Click Record
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # Initial state: must be in RECORDING
        assert window.stacked.currentIndex() == RecordingState.RECORDING.value

        # Wait with event loop running so QTimer can fire
        qtbot.wait(2500)

        # Timer label must have advanced beyond "0:00"
        assert window._recording_screen.timer_label.text() != "0:00", (
            f"timer_label must advance after 2.5s, still shows "
            f"{window._recording_screen.timer_label.text()!r}"
        )


# ---------------------------------------------------------------------------
# Phase 14d.5 — RED: DoneScreen buttons wired
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_open_folder_button_calls_os_startfile(qtbot):
    """Clicking open_folder_button reveals the ZIP parent folder.

    Phase 14d.5: open_folder_button.clicked must trigger an OS-specific file
    manager reveal:
    - Windows: os.startfile(zip_path.parent)
    - macOS: subprocess.run(["open", "-R", str(zip_path)])

    Verifies (platform-specific mock): the appropriate call is made with
    the ZIP's parent directory.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    zip_path = Path("C:/Users/test/recordings/session.zip")
    window._done_screen.set_zip_path(zip_path)
    # Also store it on the window so the slot can retrieve it
    window._done_screen._zip_path = zip_path

    Qt_LeftButton = __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton

    if sys.platform == "win32":
        with patch("os.startfile") as mock_startfile:
            qtbot.mouseClick(window._done_screen._open_folder_button, Qt_LeftButton)
            mock_startfile.assert_called_once_with(zip_path.parent)
    else:
        with patch("subprocess.run") as mock_run:
            qtbot.mouseClick(window._done_screen._open_folder_button, Qt_LeftButton)
            mock_run.assert_called_once_with(["open", "-R", str(zip_path)])


@pytest.mark.gui
def test_record_again_button_transitions_to_idle(qtbot):
    """Clicking record_again_button transitions DoneScreen → IDLE.

    Phase 14d.5: record_again_button.clicked must emit record_again signal
    (which the state machine maps DONE → IDLE).

    Verifies:
    - Start in DONE state
    - Click record_again_button
    - State transitions to IDLE
    """
    window = MainWindow()
    qtbot.addWidget(window)

    # Drive to DONE state directly
    window.start_recording.emit()
    window.stop_recording.emit()
    window._on_packaging_finished(Path("/tmp/fake.zip"))
    assert window.stacked.currentIndex() == RecordingState.DONE.value

    Qt_LeftButton = __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton
    qtbot.mouseClick(window._done_screen._record_again_button, Qt_LeftButton)

    assert window.stacked.currentIndex() == RecordingState.IDLE.value, (
        f"Expected IDLE after clicking Record Again, got state {window.stacked.currentIndex()}"
    )


# ---------------------------------------------------------------------------
# Phase 14e.4 — RED: recording_error must be logged at ERROR level
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_recording_error_is_logged(qtbot, caplog):
    """_on_recording_error() logs the error message at ERROR level.

    Phase 14e.4/14e.5: Worker exceptions are invisible in the console because
    recording_error signal only updates the UI banner — there is no logger call.
    This means a fatal worker exception leaves ZERO traces in logs.

    Verifies: calling _on_recording_error("test failure") produces an ERROR-level
    log record containing "test failure" from the main_window logger.
    """
    import logging

    window = MainWindow()
    qtbot.addWidget(window)

    with caplog.at_level(logging.ERROR, logger="gameplay_recorder.ui.main_window"):
        window._on_recording_error("test failure")

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("test failure" in msg for msg in error_messages), (
        f"Expected ERROR log containing 'test failure', got records: {error_messages!r}"
    )


# ---------------------------------------------------------------------------
# Triangulation: recording_error log message also shows when error contains
# special characters / long messages
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_recording_error_is_logged_with_full_message(qtbot, caplog):
    """_on_recording_error() logs the FULL error message, not a truncated version.

    Triangulation: error messages from adb failures can be long; ensure the full
    string is logged so the user can diagnose from console output.
    """
    import logging

    window = MainWindow()
    qtbot.addWidget(window)

    long_error = (
        "AdbCommandError: device 'emulator-5554' not found; "
        "adb -s emulator-5554 shell screenrecord: exit 1"
    )

    with caplog.at_level(logging.ERROR, logger="gameplay_recorder.ui.main_window"):
        window._on_recording_error(long_error)

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("AdbCommandError" in msg for msg in error_messages), (
        f"Full error message must appear in log, got: {error_messages!r}"
    )


# ---------------------------------------------------------------------------
# Phase 5 — RED: MainWindow ScrcpyRecorder integration
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_start_recording_uses_scrcpy_recorder_not_video_segment_recorder(qtbot):
    """start_recording_session() MUST use ScrcpyRecorder, NOT VideoSegmentRecorder.

    Phase 5.1: After the pivot, ScrcpyRecorder replaces VideoSegmentRecorder entirely.

    Verifies:
    - ScrcpyRecorder is instantiated when Record is clicked.
    - VideoSegmentRecorder is NOT imported/called.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
        patch(
            "gameplay_recorder.ui.main_window.ScrcpyRecorder",
            spec=True,
        ) as MockSR,
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor"),
        patch("gameplay_recorder.ui.main_window.check_host_free_space", return_value=None),
    ):
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # ScrcpyRecorder MUST be instantiated
        MockSR.assert_called_once()
        mock_sr_instance = MockSR.return_value
        # .start() MUST be called on the ScrcpyRecorder instance
        mock_sr_instance.start.assert_called_once()


@pytest.mark.gui
def test_start_recording_passes_session_dir_gameplay_mp4_to_scrcpy_recorder(qtbot):
    """ScrcpyRecorder receives output_path == session_dir / 'gameplay.mp4'.

    Phase 5.1: Spec 'scrcpy Video Capture' — output MUST be a single gameplay.mp4
    written directly to session_dir.

    Verifies: ScrcpyRecorder is instantiated with
      serial=<device serial>
      output_path=<session_dir> / 'gameplay.mp4'
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("DEVICE-42")
    window.idle_screen.version_field.setText("2.0.0")
    window.idle_screen.player_name_field.setText("bob")

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
        patch(
            "gameplay_recorder.ui.main_window.ScrcpyRecorder",
            spec=True,
        ) as MockSR,
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor"),
        patch("gameplay_recorder.ui.main_window.check_host_free_space", return_value=None),
    ):
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        MockSR.assert_called_once()
        sr_kwargs = MockSR.call_args.kwargs

        # output_path must be session_dir / 'gameplay.mp4'
        output_path: Path = sr_kwargs.get("output_path")
        assert output_path is not None, "ScrcpyRecorder 'output_path' kwarg is missing"
        assert isinstance(output_path, Path), (
            f"ScrcpyRecorder 'output_path' must be a Path, got {type(output_path)!r}"
        )
        assert output_path.name == "gameplay.mp4", (
            f"output_path filename must be 'gameplay.mp4', got {output_path.name!r}"
        )
        # output_path parent must equal the session_dir
        assert hasattr(window, "_session_dir"), "MainWindow has no _session_dir after start"
        assert output_path.parent == window._session_dir, (
            f"output_path parent {output_path.parent!r} != session_dir {window._session_dir!r}"
        )


@pytest.mark.gui
def test_start_recording_checks_host_free_space_before_recording(qtbot):
    """start_recording_session() MUST call check_host_free_space; if error, block recording.

    Phase 5.1: Spec 'Free-Space Pre-Check' (Modified) — host disk 1 GB threshold.
    Scenario 'Insufficient storage': app shows error banner and does NOT start recording.

    Verifies:
    - check_host_free_space is called during Record click.
    - When it returns an error string, ScrcpyRecorder is NOT instantiated.
    - The error banner on IdleScreen is visible with the error message.
    - The window stays in IDLE state.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    space_error = "Host disk space low (< 1 GB free in '/recordings'). Free space before recording."

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=True),
        patch(
            "gameplay_recorder.ui.main_window.ScrcpyRecorder",
            spec=True,
        ) as MockSR,
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor"),
        patch(
            "gameplay_recorder.ui.main_window.check_host_free_space",
            return_value=space_error,
        ) as MockCHFS,
    ):
        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # check_host_free_space MUST have been called
        MockCHFS.assert_called_once()

        # ScrcpyRecorder MUST NOT be instantiated when space is low
        MockSR.assert_not_called()

        # Window MUST remain in IDLE state
        assert window.stacked.currentIndex() == RecordingState.IDLE.value, (
            f"Expected IDLE after space-check failure, got state {window.stacked.currentIndex()}"
        )

        # Error banner MUST be visible with the space error message
        assert window.idle_screen.error_banner.isVisible(), (
            "error_banner must be visible after free-space check failure"
        )
        assert "Host disk space low" in window.idle_screen.error_banner.text(), (
            f"error_banner must contain 'Host disk space low', "
            f"got: {window.idle_screen.error_banner.text()!r}"
        )


@pytest.mark.gui
def test_start_recording_no_longer_does_adb_free_space_check(qtbot):
    """start_recording_session() MUST NOT call any ADB /sdcard free-space check.

    Phase 5.1: Spec 'Free-Space Pre-Check' (Modified) — check is now HOST-side only.
    Old implementation queried device /sdcard via ADB; new implementation uses
    check_host_free_space() (host shutil.disk_usage). No ADB shell df/stat call.

    Triangulation: verifies that the host-side check is called (not ADB), and
    that no ADB shell command referencing '/sdcard' is issued during Record.

    Verifies:
    - check_host_free_space (host path) IS called.
    - adb_conn.shell() is NOT called with any '/sdcard' argument.
    """
    from gameplay_recorder.adb.connection import AdbConnection

    window = MainWindow()
    qtbot.addWidget(window)

    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("tester")

    mock_conn = MagicMock(spec=AdbConnection)

    with (
        patch(
            "gameplay_recorder.ui.main_window.AdbConnection",
            spec=AdbConnection,
        ) as MockConn,
        patch("gameplay_recorder.ui.main_window.ScrcpyRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor"),
        patch(
            "gameplay_recorder.ui.main_window.check_host_free_space",
            return_value=None,
        ) as MockCHFS,
    ):
        MockConn.select_single_device.return_value = mock_conn

        qtbot.mouseClick(
            window.idle_screen.record_button,
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton,
        )

        # Host-side check MUST be called
        MockCHFS.assert_called_once()

        # ADB shell MUST NOT have been called with '/sdcard' (no device-side space check)
        if mock_conn.shell.called:
            for call in mock_conn.shell.call_args_list:
                args = call.args[0] if call.args else ""
                assert "/sdcard" not in str(args), (
                    f"ADB shell was called with /sdcard argument: {call!r} — "
                    "free-space check must be host-side only"
                )
