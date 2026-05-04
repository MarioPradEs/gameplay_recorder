"""RED tests for MainWindow ↔ EventPersister integration (Phase 3.1).

Tests verify:
- start_recording_session() creates an empty events.jsonl at the session path
- start_recording_session() instantiates EventPersister and starts it after the monitor
- stop_recording_session() calls requestInterruption + wait on EventPersister
- stop_recording_session() calls wait() on all capture workers BEFORE PackagingWorker.start()

GREEN implementation comes in Batch 3.2.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from PySide6.QtCore import Qt

from gameplay_recorder.adb.connection import AdbConnection
from gameplay_recorder.ui.main_window import MainWindow


def _fill_required_fields(window: MainWindow) -> None:
    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("alice")


@pytest.mark.gui
def test_start_recording_session_creates_empty_events_jsonl(qtbot, tmp_path, monkeypatch):
    """REQ-EP-8: events.jsonl must exist (empty is OK) immediately after session start."""
    monkeypatch.setattr(
        "gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR",
        tmp_path,
    )

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)

    mock_conn = MagicMock(spec=AdbConnection)

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=AdbConnection) as MockConn,
        patch("gameplay_recorder.ui.main_window.ScrcpyRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor", spec=True),
        patch("gameplay_recorder.ui.main_window.EventPersister", spec=True),
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.check_host_free_space", return_value=None),
    ):
        MockConn.select_single_device.return_value = mock_conn
        qtbot.mouseClick(window.idle_screen.record_button, Qt.LeftButton)

        # The session_dir is window._session_dir
        assert window._session_dir is not None
        events_jsonl = window._session_dir / "events.jsonl"
        assert events_jsonl.exists(), (
            f"events.jsonl was not created in session_dir {window._session_dir}"
        )
        assert events_jsonl.read_text(encoding="utf-8") == "", (
            "events.jsonl must be empty at session start"
        )


@pytest.mark.gui
def test_start_recording_session_instantiates_and_starts_event_persister(
    qtbot, tmp_path, monkeypatch
):
    """EventPersister must be constructed with the monitor + the session events.jsonl,
    and started AFTER TouchEventMonitor.start()."""
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)

    mock_conn = MagicMock(spec=AdbConnection)

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=AdbConnection) as MockConn,
        patch("gameplay_recorder.ui.main_window.ScrcpyRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor", spec=True) as MockTEM,
        patch("gameplay_recorder.ui.main_window.EventPersister", spec=True) as MockEP,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.check_host_free_space", return_value=None),
    ):
        MockConn.select_single_device.return_value = mock_conn
        qtbot.mouseClick(window.idle_screen.record_button, Qt.LeftButton)

        # EventPersister must be called once
        assert MockEP.call_count == 1, f"EventPersister called {MockEP.call_count} times"

        ep_kwargs = MockEP.call_args.kwargs
        # The monitor passed is the TouchEventMonitor instance produced by MockTEM
        assert ep_kwargs.get("monitor") is MockTEM.return_value, (
            "EventPersister did not receive the TouchEventMonitor instance"
        )
        # output_path points to events.jsonl in session_dir
        out = ep_kwargs.get("output_path")
        assert out is not None
        assert out.name == "events.jsonl"
        assert out.parent == window._session_dir

        # EventPersister.start() called on the instance
        MockEP.return_value.start.assert_called_once()


@pytest.mark.gui
def test_stop_recording_session_requests_interruption_and_waits_event_persister(
    qtbot, tmp_path, monkeypatch
):
    """REQ-EP-7: stop_recording_session must call requestInterruption + wait(1000) on EventPersister."""
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)

    mock_conn = MagicMock(spec=AdbConnection)

    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=AdbConnection) as MockConn,
        patch("gameplay_recorder.ui.main_window.ScrcpyRecorder", spec=True),
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True),
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor", spec=True),
        patch("gameplay_recorder.ui.main_window.EventPersister", spec=True) as MockEP,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True),
        patch("gameplay_recorder.ui.main_window.check_host_free_space", return_value=None),
    ):
        MockConn.select_single_device.return_value = mock_conn
        qtbot.mouseClick(window.idle_screen.record_button, Qt.LeftButton)

        # Now trigger stop
        window.stop_recording_session()

        ep_instance = MockEP.return_value
        ep_instance.requestInterruption.assert_called_once()
        # wait() called with timeout 1000 (REQ-EP-7)
        ep_instance.wait.assert_called_once_with(1000)


@pytest.mark.gui
def test_stop_recording_session_waits_for_workers_before_packaging(qtbot, tmp_path, monkeypatch):
    """REQ-EP-6: PackagingWorker MUST NOT start until all capture workers' wait() returned.

    Verifies the call ordering: video_worker.wait → event_persister.wait →
    screenshot_worker.wait → THEN PackagingWorker.start().
    """
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)

    mock_conn = MagicMock(spec=AdbConnection)

    # Use a parent MagicMock so we can assert the global call order across mocks.
    with (
        patch("gameplay_recorder.ui.main_window.AdbConnection", spec=AdbConnection) as MockConn,
        patch("gameplay_recorder.ui.main_window.ScrcpyRecorder", spec=True) as MockSR,
        patch("gameplay_recorder.ui.main_window.ScreenshotCapture", spec=True) as MockSC,
        patch("gameplay_recorder.ui.main_window.TouchEventMonitor", spec=True),
        patch("gameplay_recorder.ui.main_window.EventPersister", spec=True) as MockEP,
        patch("gameplay_recorder.ui.main_window.PackagingWorker", spec=True) as MockPW,
        patch("gameplay_recorder.ui.main_window.check_host_free_space", return_value=None),
    ):
        MockConn.select_single_device.return_value = mock_conn

        # Build a parent that records call order across all relevant mocks.
        parent = MagicMock()
        parent.attach_mock(MockSR.return_value.wait, "video_wait")
        parent.attach_mock(MockEP.return_value.wait, "ep_wait")
        parent.attach_mock(MockSC.return_value.wait, "sc_wait")
        parent.attach_mock(MockPW.return_value.start, "packaging_start")

        qtbot.mouseClick(window.idle_screen.record_button, Qt.LeftButton)
        window.stop_recording_session()

        # Pull the recorded ordered calls
        names_called = [c[0] for c in parent.mock_calls]

        # Must contain all 4 in correct order
        # video_wait happens before ep_wait, before sc_wait, before packaging_start
        assert "video_wait" in names_called, "ScrcpyRecorder.wait was never called"
        assert "ep_wait" in names_called, "EventPersister.wait was never called"
        assert "sc_wait" in names_called, "ScreenshotCapture.wait was never called"
        assert "packaging_start" in names_called, "PackagingWorker.start was never called"

        idx_video = names_called.index("video_wait")
        idx_ep = names_called.index("ep_wait")
        idx_sc = names_called.index("sc_wait")
        idx_pkg = names_called.index("packaging_start")

        assert idx_video < idx_pkg, "PackagingWorker started before ScrcpyRecorder.wait"
        assert idx_ep < idx_pkg, "PackagingWorker started before EventPersister.wait"
        assert idx_sc < idx_pkg, "PackagingWorker started before ScreenshotCapture.wait"

        # Also assert specific timeouts (REQ-EP-7)
        MockSR.return_value.wait.assert_called_once_with(7000)
        MockEP.return_value.wait.assert_called_once_with(1000)
        MockSC.return_value.wait.assert_called_once_with(1000)
