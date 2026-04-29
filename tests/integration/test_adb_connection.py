"""Integration tests for AdbConnection — require a real Android device.

These tests are gated behind the ``GAMEPLAY_RECORDER_E2E`` environment variable.
Set ``GAMEPLAY_RECORDER_E2E=1`` before running pytest to include them:

    GAMEPLAY_RECORDER_E2E=1 .venv/Scripts/python.exe -m pytest tests/integration/

Without the variable, conftest.py skips all ``e2e``-marked tests automatically.

Task 3.5 — Phase 3 (ADB / Connection).
"""

from __future__ import annotations

import subprocess

import pytest

from gameplay_recorder.adb.connection import (
    AdbConnection,
    DeviceInfo,
    MultipleDevicesError,
    NoDeviceConnectedError,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _adb_device_count() -> int:
    """Return the number of devices reported by ``adb devices`` on the host."""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Output format: "List of devices attached\n<serial>\t<state>\n..."
        lines = [
            line
            for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("List of devices")
        ]
        return len(lines)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0


# ─── Smoke tests (require GAMEPLAY_RECORDER_E2E=1) ────────────────────────────


@pytest.mark.e2e
def test_list_devices_returns_list():
    """AdbConnection.list_devices() must return a list (possibly empty).

    This test verifies the basic contract: the call succeeds and the return
    type is a list.  A real ADB server must be reachable on 127.0.0.1:5037.
    """
    conn = AdbConnection()
    devices = conn.list_devices()

    assert isinstance(devices, list), "list_devices() must return a list"


@pytest.mark.e2e
def test_list_devices_items_are_device_info():
    """Each item returned by list_devices() must be a DeviceInfo instance.

    Validates that the mapping from adbutils device entries produces the
    correct domain type with ``serial`` and ``state`` fields.
    """
    conn = AdbConnection()
    devices = conn.list_devices()

    for device in devices:
        assert isinstance(device, DeviceInfo), f"Expected DeviceInfo, got {type(device)}"
        assert isinstance(device.serial, str), "DeviceInfo.serial must be a str"
        assert isinstance(device.state, str), "DeviceInfo.state must be a str"
        assert device.serial, "DeviceInfo.serial must not be empty"


@pytest.mark.e2e
@pytest.mark.skipif(
    _adb_device_count() != 1,
    reason="Exactly one ADB device required for select_single_device() smoke test",
)
def test_select_single_device_returns_connection():
    """select_single_device() returns a connected AdbConnection when exactly one device is present.

    This is the happy-path smoke test for the classmethod factory.
    Spec: Requirement 'ADB Device Discovery', Scenario 'Single device connected'.
    """
    conn = AdbConnection.select_single_device()

    assert conn is not None, "select_single_device() must not return None"
    assert conn._serial is not None, "The returned connection must have a serial"
    assert isinstance(conn._serial, str), "serial must be a str"


@pytest.mark.e2e
@pytest.mark.skipif(
    _adb_device_count() != 0,
    reason="Zero ADB devices required for NoDeviceConnectedError smoke test",
)
def test_select_single_device_raises_no_device_when_empty():
    """select_single_device() raises NoDeviceConnectedError when no device is connected.

    Spec: Requirement 'ADB Device Discovery', Scenario 'No device connected'.
    """
    with pytest.raises(NoDeviceConnectedError):
        AdbConnection.select_single_device()


@pytest.mark.e2e
@pytest.mark.skipif(
    _adb_device_count() < 2,
    reason="Two or more ADB devices required for MultipleDevicesError smoke test",
)
def test_select_single_device_raises_multiple_devices():
    """select_single_device() raises MultipleDevicesError and exposes .serials.

    Covers the case where multiple devices are simultaneously connected.

    Spec: Requirement 'ADB Device Discovery', Scenario 'Multiple devices connected'.
    """
    with pytest.raises(MultipleDevicesError) as exc_info:
        AdbConnection.select_single_device()

    err = exc_info.value
    assert hasattr(err, "serials"), "MultipleDevicesError must expose .serials"
    assert len(err.serials) >= 2, "Must report at least 2 serials"
    for serial in err.serials:
        assert isinstance(serial, str), "Each serial in .serials must be a str"
