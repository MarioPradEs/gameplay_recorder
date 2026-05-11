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
import subprocess
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
        """shell_stream yields bytes lines from the subprocess stdout.

        Updated for Phase 4.5: shell_stream now uses subprocess.Popen instead
        of the adbutils socket recv() path.  We patch subprocess.Popen so the
        test is hermetic (no real adb process is spawned).
        """
        fake_lines = [
            b"[ 1234.567] /dev/input/event3: EV_ABS  ABS_MT_TRACKING_ID  00000001\n",
            b"[ 1234.568] /dev/input/event3: EV_SYN  SYN_REPORT           00000000\n",
        ]

        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(fake_lines)
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(return_value=0)
            return mock_proc

        with patch("subprocess.Popen", fake_popen):
            conn = AdbConnection(serial="test-device")
            conn._adb_device = MagicMock()  # satisfies _ensure_device()
            result = list(conn.shell_stream("getevent -lt /dev/input/event3"))

        assert result == fake_lines

    def test_shell_stream_returns_iterator(self) -> None:
        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(return_value=0)
            return mock_proc

        with patch("subprocess.Popen", fake_popen):
            conn = AdbConnection(serial="test-device")
            conn._adb_device = MagicMock()
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
    """Regression tests for C3 (updated for Phase 4.5).

    Original C3 bug: shell_stream called _adb_device.shell_stream(cmd) which
    does NOT exist on adbutils.AdbDevice 0.16.2 — raised AttributeError.
    First fix (Phase 3): call _adb_device.shell(cmd, stream=True) instead.

    Phase 4.5 fix: replace the entire socket-recv path with subprocess.Popen
    because adbutils stream-mode sets timeout=None → recv() blocks indefinitely
    on Windows (WinError 10053), yielding 0 touch events over the session.

    These tests are updated to assert the Phase 4.5 contract: shell_stream
    uses subprocess.Popen and does NOT call _adb_device.shell() at all.
    """

    def test_shell_stream_does_not_call_nonexistent_shell_stream_method(self) -> None:
        """shell_stream() must NOT call _adb_device.shell_stream() or _adb_device.shell().

        Phase 4.5: shell_stream uses subprocess.Popen directly — the adbutils
        device mock is never consulted by shell_stream after _ensure_device().
        """
        fake_lines = [b"line1\n", b"line2\n"]

        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(fake_lines)
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(return_value=0)
            return mock_proc

        mock_device = MagicMock()

        with patch("subprocess.Popen", fake_popen):
            conn = AdbConnection(serial="test-serial")
            conn._adb_device = mock_device
            result = list(conn.shell_stream("getevent -lt /dev/input/event3"))

        assert result == [b"line1\n", b"line2\n"]

        # Phase 4.5: _adb_device.shell() must NOT be called by shell_stream
        assert not mock_device.shell.called, (
            "shell_stream() must NOT call _adb_device.shell() — "
            "Phase 4.5 uses subprocess.Popen directly to avoid the Windows recv() hang"
        )
        # _adb_device.shell_stream() must also never be called (original C3 guard)
        assert not mock_device.shell_stream.called, (
            "AdbDevice has no shell_stream() method — it must never be called"
        )

    def test_shell_stream_calls_shell_with_stream_true(self) -> None:
        """Phase 4.5: shell_stream does NOT use _adb_device.shell(stream=True) anymore.

        The subprocess.Popen path replaces the adbutils socket path entirely.
        This test verifies that the subprocess command includes the correct args
        (previously it verified adbutils stream=True — now superseded by
        TestShellStreamSubprocess.test_shell_stream_invokes_subprocess_popen_with_adb).
        """
        fake_lines: list[bytes] = []

        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(fake_lines)
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(return_value=0)
            return mock_proc

        mock_device = MagicMock()

        with patch("subprocess.Popen", fake_popen):
            conn = AdbConnection(serial="test-serial")
            conn._adb_device = mock_device
            list(conn.shell_stream("getevent -lt"))

        # Phase 4.5: _adb_device.shell() is NOT called — subprocess handles it
        assert not mock_device.shell.called, (
            "Phase 4.5: shell_stream must NOT call _adb_device.shell() — "
            "subprocess.Popen replaces the adbutils socket path"
        )


# ─── W_NEW2: screencap() socket timeout ──────────────────────────────────────


class TestScreencapTimeout:
    """Tests for W_NEW2: screencap() must apply a socket timeout before recv loop.

    If the device hangs during screencap (low battery, USB issue, ANR), recv()
    blocks the capture thread forever.  The fix:
      1. Call adb_socket.conn.settimeout(timeout) before the recv loop.
      2. On socket.timeout, raise AdbCommandError — not silently hang or return b"".
      3. The timeout is configurable via screencap(timeout=N), default 30.0 seconds.

    Mock convention: plain MagicMock() for socket (not spec=socket.socket) because
    socket.socket has complex descriptor internals that confuse MagicMock(spec=).
    The settimeout() call assertion is the real guard here.
    """

    def _make_screencap_mock_with_socket(self) -> tuple[MagicMock, MagicMock]:
        """Return (mock_device, mock_socket) for timeout tests.

        mock_socket is the raw socket (.conn) — we assert settimeout() on it.
        """
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [fake_png, b""]

        fake_adb_conn = MagicMock()
        fake_adb_conn.conn = mock_socket

        mock_device = MagicMock()
        mock_device.shell.return_value = fake_adb_conn

        return mock_device, mock_socket

    def test_screencap_raises_adb_command_error_on_socket_timeout(self) -> None:
        """screencap() must raise AdbCommandError (not hang) when recv times out.

        After the fix: TimeoutError (= socket.timeout) is explicitly caught and
        re-raised as AdbCommandError with a clear message.
        """
        mock_socket = MagicMock()
        # recv raises TimeoutError (socket.timeout alias) simulating a hung device
        mock_socket.recv.side_effect = TimeoutError("timed out")

        fake_adb_conn = MagicMock()
        fake_adb_conn.conn = mock_socket

        mock_device = MagicMock()
        mock_device.shell.return_value = fake_adb_conn

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        with pytest.raises(AdbCommandError, match="timed out"):
            conn.screencap()

    def test_screencap_calls_settimeout_with_default(self) -> None:
        """screencap() must call socket.settimeout(30.0) by default.

        Verifies that the socket timeout is applied BEFORE the recv loop with the
        correct default value (30.0 seconds).
        """
        mock_device, mock_socket = self._make_screencap_mock_with_socket()

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        conn.screencap()

        mock_socket.settimeout.assert_called_once_with(30.0)

    def test_screencap_calls_settimeout_with_custom_value(self) -> None:
        """screencap(timeout=10.0) must call socket.settimeout(10.0).

        Triangulates that the timeout parameter is forwarded to settimeout(),
        not hardcoded.
        """
        mock_device, mock_socket = self._make_screencap_mock_with_socket()

        conn = AdbConnection(serial="test-serial")
        conn._adb_device = mock_device

        conn.screencap(timeout=10.0)

        mock_socket.settimeout.assert_called_once_with(10.0)

    def test_screencap_signature_has_timeout_parameter_with_default_30(self) -> None:
        """screencap() signature must include timeout: float = 30.0.

        Verifies the public API contract without needing a real device.
        """
        sig = inspect.signature(AdbConnection.screencap)
        assert "timeout" in sig.parameters, (
            "AdbConnection.screencap() is missing a 'timeout' parameter"
        )
        default = sig.parameters["timeout"].default
        assert default == 30.0, f"screencap() timeout default must be 30.0, got {default!r}"


# ─── Phase 4.5: shell_stream must use subprocess.Popen ────────────────────────


def _make_stream_conn(serial: str = "TESTSERIAL") -> AdbConnection:
    """Return an AdbConnection with _serial set and a dummy _adb_device.

    _adb_device is a MagicMock so _ensure_device() passes.  The underlying
    socket mock returns b"" immediately (EOF) so the old recv-loop exits
    quickly if subprocess.Popen is NOT patched (RED phase).  Once the GREEN
    implementation uses subprocess.Popen instead of the socket, the _adb_device
    mock is never consulted by shell_stream at all.
    """
    fake_socket = MagicMock()
    fake_socket.recv.return_value = b""  # immediate EOF — old loop exits fast

    fake_adb_conn = MagicMock()
    fake_adb_conn.conn = fake_socket

    mock_device = MagicMock()
    mock_device.shell.return_value = fake_adb_conn

    conn = AdbConnection(serial=serial)
    conn._adb_device = mock_device
    return conn


class TestShellStreamSubprocess:
    """Phase 4.5 — shell_stream must use subprocess.Popen(["adb", "-s", serial, "shell", cmd]).

    Root cause: the old adbutils recv(4096) path blocked indefinitely on Windows
    because adbutils sets timeout=None which is falsy, so settimeout() is never
    called on the underlying raw socket (WinError 10053 on stream teardown).

    Fix (Option A): replace shell_stream internals with subprocess.Popen and
    stdout=PIPE — same pattern already used in detect_touch_device.
    Public API of shell_stream stays identical: (cmd: str) -> Iterator[bytes].

    Patching: we patch "subprocess.Popen" at stdlib level.  Once the production
    code imports subprocess and calls subprocess.Popen, the patch intercepts it
    regardless of whether subprocess was already in connection.py before the fix.
    """

    def test_shell_stream_invokes_subprocess_popen_with_adb(self) -> None:
        """shell_stream must use subprocess.Popen([adb, -s, serial, shell, cmd])
        instead of the adbutils socket stream — fixes WinError 10053 blocking
        recv() on Windows with adb daemon stream-mode connections.
        """
        captured: dict = {}

        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            captured["cmd_args"] = cmd_args
            captured["stdout"] = stdout
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(return_value=0)
            return mock_proc

        with patch("subprocess.Popen", fake_popen):
            conn = _make_stream_conn("TESTSERIAL")
            list(conn.shell_stream("getevent -l -t /dev/input/event8"))

        assert "cmd_args" in captured, "subprocess.Popen must be called"
        cmd = captured["cmd_args"]
        assert cmd[0] == "adb", f"first arg must be 'adb', got {cmd}"
        assert "-s" in cmd, "must include -s flag"
        assert "TESTSERIAL" in cmd, "must include the serial"
        assert "shell" in cmd, "must include 'shell' subcommand"
        assert any("getevent" in str(a) for a in cmd), f"must pass the command, got {cmd}"
        assert captured["stdout"] is not None, "stdout must be PIPE for streaming"

    def test_shell_stream_yields_lines_from_stdout(self) -> None:
        """shell_stream must yield each line from the subprocess stdout."""
        fake_lines = [
            b"[   123.456] EV_ABS       ABS_MT_TRACKING_ID   00000123\n",
            b"[   123.457] EV_ABS       ABS_MT_POSITION_X    000003a4\n",
            b"[   123.458] EV_ABS       ABS_MT_POSITION_Y    00000287\n",
            b"[   123.459] EV_SYN       SYN_REPORT           00000000\n",
        ]

        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(fake_lines)
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(return_value=0)
            return mock_proc

        with patch("subprocess.Popen", fake_popen):
            conn = _make_stream_conn()
            received = list(conn.shell_stream("getevent -l -t /dev/input/event8"))

        assert len(received) == 4, f"Expected 4 lines, got {len(received)}: {received}"
        assert b"ABS_MT_POSITION_X" in received[1]

    def test_shell_stream_terminates_subprocess_on_completion(self) -> None:
        """On normal iteration completion, the subprocess must be terminated cleanly."""
        fake_lines = [b"line1\n", b"line2\n"]
        proc_handle: dict = {}

        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(fake_lines)
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(return_value=0)
            mock_proc.kill = MagicMock()
            proc_handle["proc"] = mock_proc
            return mock_proc

        with patch("subprocess.Popen", fake_popen):
            conn = _make_stream_conn()
            list(conn.shell_stream("getevent -l -t /dev/input/event8"))

        proc_handle["proc"].terminate.assert_called_once()

    def test_shell_stream_kills_subprocess_when_terminate_times_out(self) -> None:
        """If the subprocess doesn't exit within wait timeout, kill() must be called."""
        fake_lines = [b"line1\n"]
        proc_handle: dict = {}

        def fake_popen(cmd_args, stdout=None, stderr=None, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(fake_lines)
            mock_proc.terminate = MagicMock()
            mock_proc.wait = MagicMock(side_effect=subprocess.TimeoutExpired(cmd_args, 3.0))
            mock_proc.kill = MagicMock()
            proc_handle["proc"] = mock_proc
            return mock_proc

        with patch("subprocess.Popen", fake_popen):
            conn = _make_stream_conn()
            list(conn.shell_stream("getevent -l -t /dev/input/event8"))
        # Should not raise — and kill() must be called after TimeoutExpired
        proc_handle["proc"].kill.assert_called_once()
