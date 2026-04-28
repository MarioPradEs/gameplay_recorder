"""ADB connection module — public-safe ADB interface for gameplay_recorder.

Provides device discovery, screencap, and getevent streaming.
Intentionally excludes ALL input-injection methods (tap, swipe, etc.) to prevent
any private bot-neuronal IP from leaking into the public repo.

Depends only on adbutils. No numpy, PIL, or OpenCV.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

try:
    import adbutils
except ImportError:
    adbutils = None  # type: ignore[assignment]


# ─── Domain exceptions ────────────────────────────────────────────────────────


class NoDeviceConnectedError(Exception):
    """Raised when ADB discovers zero connected devices."""


class MultipleDevicesError(Exception):
    """Raised when ADB discovers more than one device.

    The ``serials`` attribute carries the list of detected device serials so
    callers can surface them to the user.
    """

    def __init__(self, serials: list[str]) -> None:
        self.serials = serials
        super().__init__(
            f"Multiple devices connected ({len(serials)}): {', '.join(serials)}. "
            "Connect exactly one device and rescan."
        )


class DeviceUnauthorizedError(Exception):
    """Raised when the connected device has not authorized the ADB host."""


class AdbCommandError(Exception):
    """Generic ADB command failure."""


# ─── Data types ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Lightweight device descriptor returned by :meth:`AdbConnection.list_devices`."""

    serial: str
    state: str


# ─── AdbConnection ────────────────────────────────────────────────────────────


class AdbConnection:
    """Thin, public-safe wrapper around adbutils.

    Exposes only what gameplay_recorder needs:
    - Device discovery (list_devices, select_single_device)
    - Raw screencap (PNG bytes)
    - Streaming shell output (shell_stream, used by TouchEventMonitor)
    - Clean shutdown (disconnect)

    There are deliberately NO tap / swipe / key-event / input-injection methods.
    """

    def __init__(
        self,
        serial: str | None = None,
        host: str = "127.0.0.1",
        port: int = 5037,
    ) -> None:
        self._serial = serial
        self._host = host
        self._port = port
        self._adb_device = None  # set lazily or via select_single_device

    # ─── Class-level factory ──────────────────────────────────────────────────

    @classmethod
    def select_single_device(
        cls,
        host: str = "127.0.0.1",
        port: int = 5037,
    ) -> AdbConnection:
        """Discover exactly one authorised device and return a ready connection.

        Raises:
            NoDeviceConnectedError: Zero devices found.
            MultipleDevicesError: More than one device found (carries serials).
            DeviceUnauthorizedError: Exactly one device found but it is unauthorized.
        """
        if adbutils is None:
            raise ImportError("adbutils not installed — run: pip install adbutils")

        client = adbutils.AdbClient(host=host, port=port)
        devices = client.list()

        if not devices:
            raise NoDeviceConnectedError(
                "No ADB device detected. Ensure the device is connected, "
                "USB Debugging is enabled, and the ADB server is running."
            )

        if len(devices) > 1:
            serials = [d.serial for d in devices]
            raise MultipleDevicesError(serials)

        device = devices[0]
        if getattr(device, "state", "device") == "unauthorized":
            raise DeviceUnauthorizedError(
                f"Device {device.serial!r} is unauthorized. "
                "Tap 'Allow' on the device screen and rescan."
            )

        conn = cls(serial=device.serial, host=host, port=port)
        conn._adb_device = client.device(device.serial)
        return conn

    # ─── Device listing ───────────────────────────────────────────────────────

    def list_devices(self) -> list[DeviceInfo]:
        """Return all currently visible ADB devices.

        Returns an empty list if no devices are connected.  Does not raise.
        """
        if adbutils is None:
            return []

        client = adbutils.AdbClient(host=self._host, port=self._port)
        raw = client.list()
        return [DeviceInfo(serial=d.serial, state=getattr(d, "state", "device")) for d in raw]

    # ─── Screen capture ───────────────────────────────────────────────────────

    def screencap(self) -> bytes:
        """Capture the device screen as raw PNG bytes.

        Uses ``adb exec-out screencap -p`` via adbutils shell.

        Returns:
            Raw PNG bytes from the device screencap.

        Raises:
            AdbCommandError: If the command fails.
        """
        self._ensure_device()
        try:
            return self._adb_device.shell("screencap -p", encoding=None)
        except Exception as exc:
            raise AdbCommandError(f"screencap failed: {exc}") from exc

    # ─── Streaming shell ──────────────────────────────────────────────────────

    def shell_stream(self, command: str) -> Iterator[bytes]:
        """Stream the output of a long-running ADB shell command.

        Yields raw output chunks (bytes) line by line until the command
        terminates or the caller stops iterating.  Used by
        :class:`~gameplay_recorder.capture.event_monitor.TouchEventMonitor`
        to consume the ``getevent -lt`` stream.

        Args:
            command: Shell command to execute (e.g. ``"getevent -lt /dev/input/event3"``).

        Yields:
            Bytes chunks / lines from the command output.
        """
        self._ensure_device()
        yield from self._adb_device.shell_stream(command)

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def disconnect(self) -> None:
        """Release the ADB device handle.

        Safe to call even if not connected.  After this call,
        screencap() and shell_stream() will raise until the connection
        is re-established.
        """
        self._adb_device = None

    def is_connected(self) -> bool:
        """Return True if a device handle is held and reachable."""
        if self._adb_device is None:
            return False
        try:
            state = self._adb_device.get_state()
            return state == "device"
        except Exception:
            return False

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _ensure_device(self) -> None:
        """Raise AdbCommandError if no device handle is set."""
        if self._adb_device is None:
            raise AdbCommandError("No ADB device connected. Call select_single_device() first.")
