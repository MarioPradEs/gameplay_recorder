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

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gameplay_recorder.models.session import RecordingState
from gameplay_recorder.ui.main_window import MainWindow

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
