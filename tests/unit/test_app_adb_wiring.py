"""RED phase — Phase 14b.3: ADB discovery wiring in main().

Tests that main() calls discover_device() on startup and propagates the result
to idle_screen.set_device_status().

Spec references:
  - Requirement "ADB Device Discovery": discover device at app start.
  - Requirement "GUI State Machine": Record button gating on device presence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Test 1 — main() calls discover_device() and sets status with found serial
# ---------------------------------------------------------------------------


def test_main_calls_discover_device_on_startup():
    """main() calls discover_device() exactly once on startup and wires the serial.

    Spec: ADB discovery must run before show() so Record button state is
    correct when the window first appears.
    """
    with (
        patch(
            "gameplay_recorder.app.discover_device", return_value=("EMULATOR-1", None)
        ) as mock_discover,
        patch("gameplay_recorder.app.detect_touch_device", return_value=None),
        patch("gameplay_recorder.app.MainWindow") as MockMainWindow,
        patch("gameplay_recorder.app.QApplication") as MockQApp,
    ):
        # Set up the QApplication mock so create_app() returns something exec()-able
        mock_app_instance = MagicMock()
        mock_app_instance.exec.return_value = 0
        MockQApp.instance.return_value = mock_app_instance

        mock_window = MagicMock()
        MockMainWindow.return_value = mock_window

        from gameplay_recorder.app import main

        main()

        mock_discover.assert_called_once()
        mock_window.idle_screen.set_device_status.assert_called_once_with("EMULATOR-1")


# ---------------------------------------------------------------------------
# Test 4 — main() detects touch device and propagates to idle_screen
# ---------------------------------------------------------------------------


def test_main_calls_detect_touch_device_when_serial_found():
    """main() invokes detect_touch_device(serial) when a device is found
    and propagates the result to idle_screen.set_touch_device().

    Spec: Phase 4 escape-hatch — IdleScreen needs the touch device path
    on startup so the Record button enabled state is correct on first
    render. Without this wiring the form is permanently locked even when
    a real touchscreen exists.
    """
    with (
        patch("gameplay_recorder.app.discover_device", return_value=("EMULATOR-1", None)),
        patch(
            "gameplay_recorder.app.detect_touch_device",
            return_value="/dev/input/event8",
        ) as mock_detect,
        patch("gameplay_recorder.app.MainWindow") as MockMainWindow,
        patch("gameplay_recorder.app.QApplication") as MockQApp,
    ):
        mock_app_instance = MagicMock()
        mock_app_instance.exec.return_value = 0
        MockQApp.instance.return_value = mock_app_instance

        mock_window = MagicMock()
        MockMainWindow.return_value = mock_window

        from gameplay_recorder.app import main

        main()

        mock_detect.assert_called_once_with("EMULATOR-1")
        mock_window.idle_screen.set_touch_device.assert_called_once_with("/dev/input/event8")


def test_main_skips_touch_detection_when_no_device():
    """main() does NOT invoke detect_touch_device() when no serial was found,
    and calls set_touch_device(None) instead.

    Spec: skip subprocess work when there's nothing to query; UI shows
    escape-hatch as expected.
    """
    with (
        patch(
            "gameplay_recorder.app.discover_device",
            return_value=(None, "No device connected"),
        ),
        patch("gameplay_recorder.app.detect_touch_device") as mock_detect,
        patch("gameplay_recorder.app.MainWindow") as MockMainWindow,
        patch("gameplay_recorder.app.QApplication") as MockQApp,
    ):
        mock_app_instance = MagicMock()
        mock_app_instance.exec.return_value = 0
        MockQApp.instance.return_value = mock_app_instance

        mock_window = MagicMock()
        MockMainWindow.return_value = mock_window

        from gameplay_recorder.app import main

        main()

        mock_detect.assert_not_called()
        mock_window.idle_screen.set_touch_device.assert_called_once_with(None)


def test_main_handles_touch_detection_error_gracefully():
    """main() swallows exceptions from detect_touch_device() and falls back
    to set_touch_device(None) so the escape-hatch UI surfaces instead of
    a hard crash.
    """
    with (
        patch("gameplay_recorder.app.discover_device", return_value=("EMULATOR-1", None)),
        patch(
            "gameplay_recorder.app.detect_touch_device",
            side_effect=RuntimeError("adb getevent crashed"),
        ) as mock_detect,
        patch("gameplay_recorder.app.MainWindow") as MockMainWindow,
        patch("gameplay_recorder.app.QApplication") as MockQApp,
    ):
        mock_app_instance = MagicMock()
        mock_app_instance.exec.return_value = 0
        MockQApp.instance.return_value = mock_app_instance

        mock_window = MagicMock()
        MockMainWindow.return_value = mock_window

        from gameplay_recorder.app import main

        # Must not raise
        main()

        mock_detect.assert_called_once_with("EMULATOR-1")
        mock_window.idle_screen.set_touch_device.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# Test 2 — main() handles no-device gracefully
# ---------------------------------------------------------------------------


def test_main_handles_no_device_gracefully():
    """main() calls set_device_status(None) when discover_device returns no serial.

    Spec: No-device scenario must not crash — Record button stays disabled.
    """
    with (
        patch(
            "gameplay_recorder.app.discover_device",
            return_value=(None, "No device connected"),
        ) as mock_discover,
        patch("gameplay_recorder.app.detect_touch_device", return_value=None),
        patch("gameplay_recorder.app.MainWindow") as MockMainWindow,
        patch("gameplay_recorder.app.QApplication") as MockQApp,
    ):
        mock_app_instance = MagicMock()
        mock_app_instance.exec.return_value = 0
        MockQApp.instance.return_value = mock_app_instance

        mock_window = MagicMock()
        MockMainWindow.return_value = mock_window

        from gameplay_recorder.app import main

        main()

        mock_discover.assert_called_once()
        mock_window.idle_screen.set_device_status.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# Test 3 — main() handles ADB error gracefully (no exception propagates)
# ---------------------------------------------------------------------------


def test_main_handles_adb_error_gracefully():
    """main() swallows exceptions from discover_device() and calls set_device_status(None).

    Spec: ADB crashes must not propagate to the user — silent swallow with fallback.
    """
    with (
        patch(
            "gameplay_recorder.app.discover_device", side_effect=RuntimeError("adb crashed")
        ) as mock_discover,
        patch("gameplay_recorder.app.detect_touch_device", return_value=None),
        patch("gameplay_recorder.app.MainWindow") as MockMainWindow,
        patch("gameplay_recorder.app.QApplication") as MockQApp,
    ):
        mock_app_instance = MagicMock()
        mock_app_instance.exec.return_value = 0
        MockQApp.instance.return_value = mock_app_instance

        mock_window = MagicMock()
        MockMainWindow.return_value = mock_window

        from gameplay_recorder.app import main

        # Must not raise
        main()

        mock_discover.assert_called_once()
        mock_window.idle_screen.set_device_status.assert_called_once_with(None)
