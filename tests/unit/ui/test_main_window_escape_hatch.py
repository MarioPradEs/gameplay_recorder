"""RED tests for MainWindow escape-hatch integration (Phase 4.1).

Tests:
- start_recording_session skips TouchEventMonitor + EventPersister when escape-hatch active
- Normal flow still spawns TouchEventMonitor + EventPersister (regression)
- validation_warning signal from ScrcpyRecorder connected to UI surface

Spec: Phase 4 — conditional monitor spawn + validation warning surface.
gameplay-recorder-shutdown-and-touch-fixes change.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt

from gameplay_recorder.adb.connection import AdbConnection
from gameplay_recorder.ui.main_window import MainWindow


def _fill_required_fields(window: MainWindow) -> None:
    """Set the minimum required fields so record_button becomes enabled."""
    window.idle_screen.set_device_status("EMU-1")
    window.idle_screen.version_field.setText("1.0.0")
    window.idle_screen.player_name_field.setText("alice")


@pytest.mark.gui
def test_recording_starts_without_touch_monitor_when_escape_hatch_active(
    qtbot, tmp_path, monkeypatch
):
    """When escape-hatch is active, TouchEventMonitor is NOT instantiated.

    Spec: Phase 4 — conditional spawn: skip TouchEventMonitor + EventPersister
    when idle_screen.escape_hatch_active is True.
    """
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)

    # Activate escape hatch: set no touch device, then check the checkbox
    window.idle_screen.set_touch_device(None)
    window.idle_screen.escape_hatch_checkbox.setCheckState(Qt.CheckState.Checked)

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

        # TouchEventMonitor and EventPersister must NOT be constructed
        assert MockTEM.call_count == 0, (
            f"TouchEventMonitor should NOT be instantiated when escape-hatch active, "
            f"got {MockTEM.call_count} call(s)"
        )
        assert MockEP.call_count == 0, (
            f"EventPersister should NOT be instantiated when escape-hatch active, "
            f"got {MockEP.call_count} call(s)"
        )


@pytest.mark.gui
def test_recording_starts_with_touch_monitor_when_device_detected(qtbot, tmp_path, monkeypatch):
    """Regression: normal flow (touch device present) still spawns TouchEventMonitor.

    Spec: Phase 4 — escape-hatch must NOT affect normal flow.
    """
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)

    # Normal flow: touch device detected, escape hatch NOT active
    window.idle_screen.set_touch_device("/dev/input/event8")

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

        # Normal flow: both should be constructed
        assert MockTEM.call_count == 1, (
            f"TouchEventMonitor SHOULD be instantiated in normal flow, "
            f"got {MockTEM.call_count} call(s)"
        )
        assert MockEP.call_count == 1, (
            f"EventPersister SHOULD be instantiated in normal flow, got {MockEP.call_count} call(s)"
        )


@pytest.mark.gui
def test_validation_warning_signal_connected_to_ui(qtbot, tmp_path, monkeypatch):
    """When ScrcpyRecorder emits validation_warning, the UI surfaces it.

    Spec: Phase 4 — validation_warning signal from Batch 2 must be wired to
    a visible UI indicator (status bar or label).
    """
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)
    window.idle_screen.set_touch_device("/dev/input/event8")

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

        # Simulate the recorder emitting validation_warning directly via the slot
        warning_msg = "mp4 missing moov atom — file may be unplayable"
        window._on_validation_warning(warning_msg)

        # The warning must appear somewhere visible. We check the status bar message
        # or the idle_screen error_banner or a dedicated validation warning label.
        # The spec says "simplest visible surface" — we expect statusBar text.
        status_text = window.statusBar().currentMessage()
        assert warning_msg in status_text, (
            f"Expected '{warning_msg}' in status bar, got: {status_text!r}"
        )


@pytest.mark.gui
def test_touch_capture_active_false_when_escape_hatch(qtbot, tmp_path, monkeypatch):
    """When recording with escape-hatch, _touch_capture_active is False.

    Spec: Phase 4 — MainWindow tracks touch_capture state for session_meta.
    """
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)
    window.idle_screen.set_touch_device(None)
    window.idle_screen.escape_hatch_checkbox.setCheckState(Qt.CheckState.Checked)

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

        assert window._touch_capture_active is False


@pytest.mark.gui
def test_touch_capture_active_true_when_normal_recording(qtbot, tmp_path, monkeypatch):
    """When recording normally (touch device present), _touch_capture_active is True.

    Triangulation: contrast with escape-hatch path.
    """
    monkeypatch.setattr("gameplay_recorder.ui.main_window.DEFAULT_OUTPUT_DIR", tmp_path)

    window = MainWindow()
    qtbot.addWidget(window)
    _fill_required_fields(window)
    window.idle_screen.set_touch_device("/dev/input/event8")

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

        assert window._touch_capture_active is True
