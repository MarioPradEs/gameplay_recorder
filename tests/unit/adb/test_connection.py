"""Unit tests for adb/connection.py — AdbConnection class.

Tests cover:
- list_devices: empty, single, multiple
- select_single_device: happy path, no device, multiple, unauthorized
- screencap: returns PNG bytes
- shell_stream: yields lines
- disconnect: clean shutdown
- IP firewall: no input injection methods on AdbConnection
- Edge cases: MultipleDevicesError carries serials, DeviceInfo fields, screencap error path
- Regression: AdbClient.list() does not exist — spec-checked mocks catch API drift
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import adbutils
import pytest
from adbutils._proto import DeviceEvent

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
            mock_adb.AdbClient.return_value = MagicMock()
            with patch(
                "gameplay_recorder.adb.connection._list_all_devices",
                return_value=[],
            ):
                conn = AdbConnection()
                result = conn.list_devices()

        assert result == []

    def test_list_devices_returns_single_device_when_one_connected(self) -> None:
        fake_events = [DeviceEvent(present=True, serial="abc123", status="device")]

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_adb.AdbClient.return_value = MagicMock()
            with patch(
                "gameplay_recorder.adb.connection._list_all_devices",
                return_value=fake_events,
            ):
                conn = AdbConnection()
                result = conn.list_devices()

        assert len(result) == 1
        assert result[0].serial == "abc123"
        assert result[0].state == "device"

    def test_list_devices_returns_multiple_when_two_connected(self) -> None:
        fake_events = [
            DeviceEvent(present=True, serial="device-A", status="device"),
            DeviceEvent(present=True, serial="device-B", status="device"),
        ]

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_adb.AdbClient.return_value = MagicMock()
            with patch(
                "gameplay_recorder.adb.connection._list_all_devices",
                return_value=fake_events,
            ):
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
            mock_client.device_list.return_value = [device]
            mock_adb.AdbClient.return_value = mock_client

            conn = AdbConnection.select_single_device()

        assert conn._serial == "ok-device"

    def test_select_single_device_raises_no_device_when_zero(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            mock_client.device_list.return_value = []
            mock_adb.AdbClient.return_value = mock_client
            with patch(
                "gameplay_recorder.adb.connection._list_all_devices",
                return_value=[],
            ):
                with pytest.raises(NoDeviceConnectedError):
                    AdbConnection.select_single_device()

    def test_select_single_device_raises_multiple_devices_with_serials_listed(self) -> None:
        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            d1 = _make_device("serial-X", "device")
            d2 = _make_device("serial-Y", "device")
            mock_client.device_list.return_value = [d1, d2]
            mock_adb.AdbClient.return_value = mock_client

            with pytest.raises(MultipleDevicesError) as exc_info:
                AdbConnection.select_single_device()

        # Exception must carry the detected serials
        assert "serial-X" in str(exc_info.value)
        assert "serial-Y" in str(exc_info.value)

    def test_select_single_device_raises_unauthorized_when_state_is_unauthorized(self) -> None:
        """DeviceUnauthorizedError is raised when device_list() is empty but an
        unauthorized device appears in the raw host:devices output."""
        unauth_event = DeviceEvent(present=True, serial="unauth-device", status="unauthorized")

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock()
            # device_list() returns only authorised devices — empty in this case
            mock_client.device_list.return_value = []
            mock_adb.AdbClient.return_value = mock_client
            with patch(
                "gameplay_recorder.adb.connection._list_all_devices",
                return_value=[unauth_event],
            ):
                with pytest.raises(DeviceUnauthorizedError):
                    AdbConnection.select_single_device()


# ─── screencap ───────────────────────────────────────────────────────────────


class TestScreencap:
    def test_screencap_returns_png_bytes(self) -> None:
        """screencap() returns the raw bytes from the device socket.

        The real API: AdbDevice.shell("screencap -p", stream=True) returns an
        adbutils.AdbConnection with a .conn socket. We read chunks until EOF.
        """
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

        # Build a mock that simulates AdbDevice.shell(stream=True) → socket → bytes
        fake_socket = MagicMock()
        fake_socket.recv.side_effect = [fake_png, b""]  # data then EOF
        fake_adb_conn = MagicMock()
        fake_adb_conn.conn = fake_socket

        mock_adb_device = MagicMock()
        mock_adb_device.shell.return_value = fake_adb_conn

        conn = AdbConnection(serial="test-device")
        conn._adb_device = mock_adb_device
        result = conn.screencap()

        assert isinstance(result, bytes)
        assert result == fake_png


# ─── shell_stream ────────────────────────────────────────────────────────────


def _make_shell_stream_mock(lines: list[bytes]) -> MagicMock:
    """Build a mock adbutils.AdbDevice whose shell(stream=True) returns a fake socket.

    The fake socket's recv() returns each line in sequence, then b"" to signal EOF.
    This matches the real adbutils._adb.AdbConnection.conn interface.
    """
    # Build recv side_effect: return each chunk then b"" for EOF
    chunks = list(lines) + [b""]
    fake_socket = MagicMock()
    fake_socket.recv.side_effect = chunks

    fake_adb_conn = MagicMock()
    fake_adb_conn.conn = fake_socket

    mock_device = MagicMock()
    mock_device.shell.return_value = fake_adb_conn
    return mock_device


class TestShellStream:
    def test_shell_stream_yields_lines_until_terminated(self) -> None:
        fake_lines = [
            b"[ 1234.567] /dev/input/event3: EV_ABS  ABS_MT_TRACKING_ID  00000001\n",
            b"[ 1234.568] /dev/input/event3: EV_SYN  SYN_REPORT           00000000\n",
        ]

        mock_adb_device = _make_shell_stream_mock(fake_lines)

        conn = AdbConnection(serial="test-device")
        conn._adb_device = mock_adb_device
        result = list(conn.shell_stream("getevent -lt /dev/input/event3"))

        assert result == fake_lines

    def test_shell_stream_returns_iterator(self) -> None:
        mock_adb_device = _make_shell_stream_mock([])

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
        conn = AdbConnection(serial="test")
        mock_device = MagicMock()
        # shell() raises — e.g. device went offline
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
            mock_client.device_list.return_value = [d1, d2]
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


# ─── Regression: spec-checked AdbClient mock (API drift guard) ───────────────


class TestAdbClientSpecChecked:
    """Regression tests that use MagicMock(spec=adbutils.AdbClient).

    A plain MagicMock accepts ANY method call (including non-existent ones like
    .list()), which is why the original bug was invisible to unit tests.

    MagicMock(spec=adbutils.AdbClient) restricts attribute access to ONLY methods
    that actually exist on AdbClient in the installed version.  If connection.py
    calls a non-existent method, these tests will fail with AttributeError — which
    is exactly the bug we're guarding against.

    Regression for: AttributeError: 'AdbClient' object has no attribute 'list'
    (adbutils 0.16.2 has device_list(), NOT list())
    """

    def test_select_single_device_does_not_call_nonexistent_list_method(self) -> None:
        """select_single_device() must NOT call client.list().

        This test will raise AttributeError if the production code calls a method
        that doesn't exist on the real adbutils.AdbClient — catching API drift.
        """
        mock_client = MagicMock(spec=adbutils.AdbClient)
        # device_list() returns a list of AdbDevice-like objects
        mock_device = MagicMock()
        mock_device.serial = "spec-checked-device"
        mock_client.device_list.return_value = [mock_device]
        mock_client.device.return_value = MagicMock()

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_adb.AdbClient.return_value = mock_client
            conn = AdbConnection.select_single_device()

        assert conn._serial == "spec-checked-device"

    def test_list_devices_does_not_call_nonexistent_list_method(self) -> None:
        """list_devices() must NOT call client.list().

        Same guard: spec-restricted mock will reject any call to .list().
        list_devices() uses _list_all_devices() (socket-level); we patch that
        helper to return a controlled list of DeviceEvent objects.
        """
        from adbutils._proto import DeviceEvent

        fake_events = [DeviceEvent(present=True, serial="spec-dev-1", status="device")]

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_client = MagicMock(spec=adbutils.AdbClient)
            mock_adb.AdbClient.return_value = mock_client
            with patch(
                "gameplay_recorder.adb.connection._list_all_devices",
                return_value=fake_events,
            ):
                conn = AdbConnection()
                result = conn.list_devices()

        assert len(result) == 1
        assert result[0].serial == "spec-dev-1"
        assert result[0].state == "device"

    def test_select_single_device_raises_no_device_with_spec_mock(self) -> None:
        """NoDeviceConnectedError is raised when device_list() and _list_all_devices() are empty."""
        mock_client = MagicMock(spec=adbutils.AdbClient)
        mock_client.device_list.return_value = []

        with patch("gameplay_recorder.adb.connection.adbutils") as mock_adb:
            mock_adb.AdbClient.return_value = mock_client
            with patch(
                "gameplay_recorder.adb.connection._list_all_devices",
                return_value=[],
            ):
                with pytest.raises(NoDeviceConnectedError):
                    AdbConnection.select_single_device()


# ─── Regression: C1 — AdbConnection.shell() must exist ──────────────────────


class TestAdbConnectionShell:
    """Regression tests for C1: AdbConnection.shell() was missing.

    video_recorder.py calls adb_conn.shell("df /sdcard") and
    adb_conn.shell("rm -f <path>"). Without this method both calls raise
    AttributeError at runtime, but plain MagicMock() silently accepts them.

    These tests use MagicMock(spec=AdbConnection) so that any call to a
    non-existent method raises AttributeError — exactly what happened in prod.
    """

    def test_adb_connection_has_shell_method(self) -> None:
        """AdbConnection must expose a shell() method (C1 regression)."""
        assert hasattr(AdbConnection, "shell"), (
            "AdbConnection.shell() is missing — video_recorder.py will AttributeError at runtime"
        )
        assert callable(getattr(AdbConnection, "shell")), "AdbConnection.shell must be callable"

    def test_shell_returns_string(self) -> None:
        """shell() must return a str (delegates to adbutils AdbDevice.shell)."""
        mock_device = MagicMock()
        mock_device.shell.return_value = "hello from device"

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        result = conn.shell("echo hello")

        assert isinstance(result, str)
        assert result == "hello from device"
        mock_device.shell.assert_called_once_with("echo hello")

    def test_shell_raises_adb_command_error_on_failure(self) -> None:
        """shell() wraps underlying exceptions in AdbCommandError."""
        mock_device = MagicMock()
        mock_device.shell.side_effect = RuntimeError("device offline")

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        with pytest.raises(AdbCommandError):
            conn.shell("df /sdcard")

    def test_shell_raises_when_no_device_connected(self) -> None:
        """shell() raises AdbCommandError if called without a device handle."""
        conn = AdbConnection(serial="test-serial")
        # _adb_device is None by default

        with pytest.raises(AdbCommandError):
            conn.shell("echo hello")

    def test_spec_checked_mock_rejects_missing_shell_method(self) -> None:
        """MagicMock(spec=AdbConnection) must HAVE shell() after the fix.

        Before the fix: AdbConnection had no shell() — this mock would reject
        any call to .shell() with AttributeError.
        After the fix: shell() exists — mock allows the call.
        """
        mock_conn = MagicMock(spec=AdbConnection)
        # After the fix, this must not raise AttributeError:
        mock_conn.shell.return_value = "some output"
        result = mock_conn.shell("df /sdcard")
        assert result == "some output"


# ─── Regression: C2 — screencap() must use correct adbutils API ─────────────


class TestScreencapCorrectApi:
    """Regression tests for C2: screencap used shell("screencap -p", encoding=None).

    Real adbutils 0.16.2 AdbDevice.shell() signature:
        shell(cmdargs, stream=False, timeout=None, rstrip=True)
    NO 'encoding' parameter — passing encoding=None raises TypeError.
    Furthermore shell() returns str by default, not bytes.

    Correct approach: use shell("screencap -p", stream=True) and read raw bytes
    from the returned AdbConnection socket.
    """

    def _make_screencap_mock(self, png_bytes: bytes) -> MagicMock:
        """Build an AdbDevice mock where shell(stream=True) returns a socket with PNG data.

        Uses plain MagicMock (not spec=AdbDevice) to avoid pytest-asyncio hang.
        The stream=True API contract is validated in the test assertions.
        """
        fake_socket = MagicMock()
        # Return PNG data in chunks then b"" for EOF
        fake_socket.recv.side_effect = [png_bytes, b""]

        fake_adb_conn = MagicMock()
        fake_adb_conn.conn = fake_socket

        mock_device = MagicMock()
        mock_device.shell.return_value = fake_adb_conn
        return mock_device

    def test_screencap_does_not_pass_encoding_kwarg(self) -> None:
        """screencap() must NOT call _adb_device.shell(encoding=None).

        Uses spec= mock to guard against wrong kwargs.
        """
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        mock_device = self._make_screencap_mock(fake_png)

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        result = conn.screencap()

        # Must return bytes
        assert isinstance(result, bytes), f"screencap() must return bytes, got {type(result)}"
        # Must NOT call shell with encoding= kwarg
        call_kwargs = mock_device.shell.call_args.kwargs if mock_device.shell.call_args else {}
        assert "encoding" not in call_kwargs, (
            "screencap() must not pass 'encoding=' to AdbDevice.shell() — "
            "that parameter does not exist in adbutils 0.16.2"
        )

    def test_screencap_uses_stream_true(self) -> None:
        """screencap() must call _adb_device.shell(..., stream=True) for binary data."""
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        mock_device = self._make_screencap_mock(fake_png)

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        conn.screencap()

        # Must call shell with stream=True
        mock_device.shell.assert_called_once()
        call_kwargs = mock_device.shell.call_args.kwargs
        call_args = mock_device.shell.call_args.args
        # stream=True must appear either as kwarg or positional arg[1]
        stream_passed = call_kwargs.get("stream") or (len(call_args) > 1 and call_args[1] is True)
        assert stream_passed, (
            "screencap() must call AdbDevice.shell(cmd, stream=True) to get binary PNG bytes"
        )


# ─── Regression: C3 — shell_stream() must use shell(stream=True) ─────────────


class TestShellStreamCorrectApi:
    """Regression tests for C3: shell_stream called _adb_device.shell_stream(cmd).

    AdbDevice has NO shell_stream() method in adbutils 0.16.2.
    Correct API: shell(cmd, stream=True) → returns adbutils.AdbConnection (socket).

    NOTE: We use plain MagicMock() here (not spec=AdbDevice) because
    MagicMock(spec=AdbDevice) triggers a hang in pytest-asyncio auto mode
    due to how pytest-asyncio inspects class attributes for coroutine detection.
    The assertion that shell_stream() is never called serves as the real guard.
    """

    def test_shell_stream_does_not_call_nonexistent_shell_stream_method(self) -> None:
        """shell_stream() must NOT call _adb_device.shell_stream().

        Before the fix: code called _adb_device.shell_stream(cmd) — a method that
        does NOT exist on adbutils.AdbDevice 0.16.2 and raises AttributeError.
        After the fix: code calls _adb_device.shell(cmd, stream=True).

        We assert that .shell_stream was NEVER called on the device mock.
        """
        # Build a socket that returns data then EOF
        fake_socket = MagicMock()
        fake_socket.recv.side_effect = [b"line1\n", b"line2\n", b""]
        fake_adb_conn = MagicMock()
        fake_adb_conn.conn = fake_socket

        mock_device = MagicMock()
        mock_device.shell.return_value = fake_adb_conn

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        result = list(conn.shell_stream("getevent -lt /dev/input/event3"))
        assert result == [b"line1\n", b"line2\n"]

        # shell_stream must NEVER be called on the underlying device (it doesn't exist)
        assert not mock_device.shell_stream.called, (
            "AdbDevice has no shell_stream() method — must use shell(cmd, stream=True). "
            "shell_stream() was called on the device mock!"
        )
        assert mock_device.shell.call_count == 1, "Must call shell() exactly once"

    def test_shell_stream_calls_shell_with_stream_true(self) -> None:
        """shell_stream() must call _adb_device.shell(cmd, stream=True)."""
        # Build a socket that immediately signals EOF
        fake_socket = MagicMock()
        fake_socket.recv.side_effect = [b""]
        fake_adb_conn = MagicMock()
        fake_adb_conn.conn = fake_socket

        mock_device = MagicMock()
        mock_device.shell.return_value = fake_adb_conn

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        list(conn.shell_stream("getevent -lt"))

        mock_device.shell.assert_called_once()
        call_kwargs = mock_device.shell.call_args.kwargs
        call_args = mock_device.shell.call_args.args
        stream_passed = call_kwargs.get("stream") or (len(call_args) > 1 and call_args[1] is True)
        assert stream_passed, "shell_stream() must call AdbDevice.shell(cmd, stream=True)"
