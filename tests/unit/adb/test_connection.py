"""Unit tests for adb/connection.py — AdbConnection class.

Tests cover:
- list_devices: empty, single, multiple
- select_single_device: happy path, no device, multiple, unauthorized
- screencap: returns PNG bytes
- shell_stream: yields lines
- disconnect: clean shutdown
- IP firewall: no input injection methods on AdbConnection
- Edge cases: MultipleDevicesError carries serials, DeviceInfo fields, screencap error path
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from gameplay_recorder.adb.connection import (
    AdbCommandError,
    AdbConnection,
    DeviceInfo,
    DeviceUnauthorizedError,
    MultipleDevicesError,
    NoDeviceConnectedError,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_device(serial: str = "emulator-5554", state: str = "device") -> MagicMock:
    """Return a mock adbutils device-info object."""
    d = MagicMock()
    d.serial = serial
    d.state = state
    return d


# ─── list_devices ─────────────────────────────────────────────────────────────


class TestListDevices:
    def test_list_devices_returns_empty_when_none_connected(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            mock_client.list.return_value = []
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection()
            result = conn.list_devices()

        assert result == []

    def test_list_devices_returns_single_device_when_one_connected(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            device = _make_device("abc123", "device")
            mock_client.list.return_value = [device]
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection()
            result = conn.list_devices()

        assert len(result) == 1
        assert result[0].serial == "abc123"
        assert result[0].state == "device"

    def test_list_devices_returns_multiple_when_two_connected(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            d1 = _make_device("device-A", "device")
            d2 = _make_device("device-B", "device")
            mock_client.list.return_value = [d1, d2]
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection()
            result = conn.list_devices()

        assert len(result) == 2
        serials = {r.serial for r in result}
        assert serials == {"device-A", "device-B"}


# ─── select_single_device ────────────────────────────────────────────────────


class TestSelectSingleDevice:
    def test_select_single_device_returns_connection_with_one_device(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            device = _make_device("ok-device", "device")
            mock_client.list.return_value = [device]
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection.select_single_device()

        assert conn._serial == "ok-device"

    def test_select_single_device_raises_no_device_when_zero(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            mock_client.list.return_value = []
            mock_adb.AdbClient.return_value = mock_client

            with pytest.raises(NoDeviceConnectedError):
                AdbConnection.select_single_device()

    def test_select_single_device_raises_multiple_devices_with_serials_listed(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            d1 = _make_device("serial-X", "device")
            d2 = _make_device("serial-Y", "device")
            mock_client.list.return_value = [d1, d2]
            mock_adb.AdbClient.return_value = mock_client

            with pytest.raises(MultipleDevicesError) as exc_info:
                AdbConnection.select_single_device()

        # Exception must carry the detected serials
        assert "serial-X" in str(exc_info.value)
        assert "serial-Y" in str(exc_info.value)

    def test_select_single_device_raises_unauthorized_when_state_is_unauthorized(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            device = _make_device("unauth-device", "unauthorized")
            mock_client.list.return_value = [device]
            mock_adb.AdbClient.return_value = mock_client

            with pytest.raises(DeviceUnauthorizedError):
                AdbConnection.select_single_device()


# ─── screencap ───────────────────────────────────────────────────────────────


class TestScreencap:
    def test_screencap_returns_png_bytes(self) -> None:
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            mock_adb_device = MagicMock()
            mock_adb_device.shell.return_value = fake_png
            mock_client.device.return_value = mock_adb_device
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection(serial="test-device")
            conn._adb_device = mock_adb_device
            result = conn.screencap()

        assert isinstance(result, bytes)
        assert result == fake_png


# ─── shell_stream ────────────────────────────────────────────────────────────


class TestShellStream:
    def test_shell_stream_yields_lines_until_terminated(self) -> None:
        fake_lines = [
            b"[ 1234.567] /dev/input/event3: EV_ABS  ABS_MT_TRACKING_ID  00000001",
            b"[ 1234.568] /dev/input/event3: EV_SYN  SYN_REPORT           00000000",
        ]

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            mock_adb_device = MagicMock()
            mock_adb_device.shell_stream.return_value = iter(fake_lines)
            mock_client.device.return_value = mock_adb_device
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection(serial="test-device")
            conn._adb_device = mock_adb_device
            result = list(conn.shell_stream("getevent -lt /dev/input/event3"))

        assert result == fake_lines

    def test_shell_stream_returns_iterator(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            mock_adb_device = MagicMock()
            mock_adb_device.shell_stream.return_value = iter([])
            mock_client.device.return_value = mock_adb_device
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection(serial="test-device")
            conn._adb_device = mock_adb_device
            result = conn.shell_stream("getevent -lt")

        # Must be an iterator/generator
        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")


# ─── disconnect ──────────────────────────────────────────────────────────────


class TestDisconnect:
    def test_disconnect_terminates_streaming_process(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            mock_adb_device = MagicMock()
            mock_client.device.return_value = mock_adb_device
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection(serial="test-device")
            conn._adb_device = mock_adb_device
            conn.disconnect()

        assert conn._adb_device is None


# ─── IP firewall — no input injection ────────────────────────────────────────


class TestNoInputInjection:
    _DENY_LIST = {"tap", "swipe", "input_text", "input_keyevent", "send_keys", "click", "press"}

    def test_adb_connection_does_not_expose_input_injection(self) -> None:
        public_methods = {
            name
            for name, _ in inspect.getmembers(AdbConnection, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        violations = public_methods & self._DENY_LIST
        assert violations == set(), (
            f"AdbConnection exposes banned input-injection method(s): {violations!r}"
        )


# ─── Edge cases / triangulation ──────────────────────────────────────────────


class TestEdgeCases:
    def test_multiple_devices_error_carries_serials_list(self) -> None:
        """MultipleDevicesError.serials must be accessible for UI error display."""
        serials = ["device-X", "device-Y", "device-Z"]
        exc = MultipleDevicesError(serials)
        assert exc.serials == serials

    def test_multiple_devices_error_message_contains_all_serials(self) -> None:
        """Error message must list every detected serial."""
        exc = MultipleDevicesError(["AAA", "BBB"])
        msg = str(exc)
        assert "AAA" in msg
        assert "BBB" in msg

    def test_device_info_is_frozen_dataclass(self) -> None:
        """DeviceInfo must be immutable so it can be safely passed across threads."""
        import dataclasses

        assert dataclasses.is_dataclass(DeviceInfo)
        info = DeviceInfo(serial="s", state="device")
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            info.serial = "mutated"  # type: ignore[misc]

    def test_screencap_raises_adb_command_error_on_failure(self) -> None:
        """screencap() must wrap underlying exceptions in AdbCommandError."""
        with patch("gameplay_recorder.adb.connection.adbutils"):
            conn = AdbConnection(serial="test")
            mock_device = MagicMock()
            mock_device.shell.side_effect = RuntimeError("device disconnected")
            conn._adb_device = mock_device

            with pytest.raises(AdbCommandError):
                conn.screencap()

    def test_list_devices_returns_empty_list_when_adbutils_unavailable(self) -> None:
        """list_devices must return [] gracefully when adbutils is None."""
        import gameplay_recorder.adb.connection as mod

        original = mod.adbutils
        try:
            mod.adbutils = None  # type: ignore[assignment]
            conn = AdbConnection()
            result = conn.list_devices()
            assert result == []
        finally:
            mod.adbutils = original

    def test_select_single_device_raises_multiple_with_exactly_two_devices(self) -> None:
        """Triangulate: ensure the threshold is >1, not just >2."""
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            d1 = _make_device("d1", "device")
            d2 = _make_device("d2", "device")
            mock_client.list.return_value = [d1, d2]
            mock_adb.AdbClient.return_value = mock_client

            with pytest.raises(MultipleDevicesError) as exc_info:
                AdbConnection.select_single_device()

        assert len(exc_info.value.serials) == 2

    def test_disconnect_makes_is_connected_return_false(self) -> None:
        """After disconnect(), is_connected() must return False without raising."""
        conn = AdbConnection(serial="any")
        # No device set — already disconnected
        conn.disconnect()
        assert conn.is_connected() is False
