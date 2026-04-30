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
# Test 2 — main() handles no-device gracefully
# ---------------------------------------------------------------------------


def test_main_handles_no_device_gracefully():
    """main() calls set_device_status(None) when discover_device returns no serial.

    Spec: No-device scenario must not crash — Record button stays disabled.
    """
    with (
        patch(
            "gameplay_recorder.app.discover_device", return_value=(None, "No device connected")
        ) as mock_discover,
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
