"""TouchEventMonitor — daemon thread that streams getevent and queues RawTouchEvents.

Adapted from bot-neuronal/recorder/event_monitor.py.
Changes:
- Import: gameplay_recorder.models.touch_event (not bot_neuronal.recorder.models)
- AdbConnection (not ADBDriver) — uses shell_stream / shell
- Field names: ts, type (not timestamp_s, action)
- Type values: "touch_down", "touch_move", "touch_up" (not "DOWN", "MOVE", "UP")
- Removed: TrainingLogger, ML labels, reward signals, gesture recognition references

Design:
- Spawns a single daemon thread that calls adb.shell_stream("getevent -l -t <node>").
- Parses each line into logical events (DOWN/MOVE/UP) via a mini state machine.
- Enqueues completed RawTouchEvent objects into a thread-safe Queue.
- When the queue is full (overflow), put_nowait() drops the item and logs a warning.
- Thread exits when stop_event is set or the stream iterator is exhausted.

getevent -l -t line format (abbreviated):
    [<timestamp>] <device>: EV_ABS  ABS_MT_SLOT          00000001
    [<timestamp>] <device>: EV_ABS  ABS_MT_TRACKING_ID   00000001   <- contact start (DOWN)
    [<timestamp>] <device>: EV_ABS  ABS_MT_POSITION_X    00000218
    [<timestamp>] <device>: EV_ABS  ABS_MT_POSITION_Y    000004a4
    [<timestamp>] <device>: EV_SYN  SYN_REPORT           00000000   <- flush -> emit event
    [<timestamp>] <device>: EV_ABS  ABS_MT_TRACKING_ID   ffffffff   <- contact end (UP)
    [<timestamp>] <device>: EV_SYN  SYN_REPORT           00000000   <- flush -> emit UP
"""

from __future__ import annotations

import logging
import queue
import re
import subprocess
import threading
from typing import TYPE_CHECKING

from gameplay_recorder.adb.paths import adb_path
from gameplay_recorder.models.touch_event import RawTouchEvent

if TYPE_CHECKING:
    from gameplay_recorder.adb.connection import AdbConnection

logger = logging.getLogger(__name__)

# ─── Domain exceptions ────────────────────────────────────────────────────────


class TouchDeviceNotFoundError(RuntimeError):
    """Raised when no touchscreen input device can be detected on the target."""


# ─── getevent line regex ──────────────────────────────────────────────────────

# Matches: "[<ts>] <dev>: EV_TYPE  EV_CODE  <hex_value>"
_LINE_RE = re.compile(
    r"\[\s*(?P<ts>[0-9.]+)\]\s+\S+:\s+(?P<ev_type>\S+)\s+(?P<ev_code>\S+)\s+(?P<value>[0-9a-fA-F]+)"
)

# Device node detection — matches the device path before the colon
_DEVICE_BLOCK_RE = re.compile(r"add device \d+:\s+(?P<node>/dev/input/\S+)")

_TRACKING_ID_INVALID = 0xFFFFFFFF  # getevent value for contact-lifted

# Scoring weights for touch device detection
_SCORE_ABS_MT_POSITION_X = 10
_SCORE_ABS_MT_POSITION_Y = 10
_SCORE_ABS_MT_TRACKING_ID = 5
_SCORE_INPUT_PROP_DIRECT = 5
_SCORE_TOUCHSCREEN_NAME = 2
_TOUCHSCREEN_NAME_KEYWORDS = ("touch", "panel", "screen")

# ─── Module-level touch device detection ─────────────────────────────────────


def detect_touch_device(serial: str) -> str | None:
    """Auto-detect the touchscreen /dev/input/eventN node on a device.

    Runs ``adb -s <serial> shell getevent -lp`` (with ``-l`` for human-readable
    labels) and applies a scoring heuristic to find the best touchscreen device.

    Scoring:
        +10 for ABS_MT_POSITION_X
        +10 for ABS_MT_POSITION_Y
        +5  for ABS_MT_TRACKING_ID
        +5  for INPUT_PROP_DIRECT
        +2  if device name contains "touch", "panel", or "screen" (case-insensitive)

    Threshold: device MUST have BOTH ABS_MT_POSITION_X and ABS_MT_POSITION_Y
    to be a candidate. Devices missing either axis are excluded entirely.

    Args:
        serial: ADB device serial (e.g. ``"17d4994b"``).

    Returns:
        Device node path (e.g. ``"/dev/input/event8"``) for the highest-scoring
        candidate, or ``None`` if no device passes the threshold.
    """
    try:
        result = subprocess.run(
            [str(adb_path()), "-s", serial, "shell", "getevent", "-lp"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout
    except Exception:
        logger.warning("detect_touch_device: adb getevent -lp failed for serial=%s", serial)
        return None

    # Parse output into device blocks.
    # Each block starts with "add device N: /dev/input/eventX"
    # and contains name, events, and input props sections.
    devices: list[dict] = []  # [{path, name, events_set}]
    current: dict | None = None

    for line in output.splitlines():
        m = _DEVICE_BLOCK_RE.search(line)
        if m:
            # Flush previous device block
            if current is not None:
                devices.append(current)
            current = {"path": m.group("node"), "name": "", "events_set": set()}
            continue

        if current is None:
            continue

        # Capture device name
        name_match = re.search(r'name:\s+"([^"]*)"', line)
        if name_match:
            current["name"] = name_match.group(1)
            continue

        # Collect all uppercase identifiers (capability labels) from this line.
        # getevent -lp outputs labels like ABS_MT_POSITION_X, INPUT_PROP_DIRECT, etc.
        labels = re.findall(r"\b([A-Z][A-Z0-9_]+)\b", line)
        current["events_set"].update(labels)

    # Don't forget the last block
    if current is not None:
        devices.append(current)

    # Score each device — threshold requires both X and Y axes
    best_path: str | None = None
    best_score: int = -1

    for dev in devices:
        events_set = dev["events_set"]
        if "ABS_MT_POSITION_X" not in events_set or "ABS_MT_POSITION_Y" not in events_set:
            continue  # does not pass threshold

        score = _SCORE_ABS_MT_POSITION_X + _SCORE_ABS_MT_POSITION_Y
        if "ABS_MT_TRACKING_ID" in events_set:
            score += _SCORE_ABS_MT_TRACKING_ID
        if "INPUT_PROP_DIRECT" in events_set:
            score += _SCORE_INPUT_PROP_DIRECT
        name_lower = dev["name"].lower()
        if any(kw in name_lower for kw in _TOUCHSCREEN_NAME_KEYWORDS):
            score += _SCORE_TOUCHSCREEN_NAME

        if score > best_score:
            best_score = score
            best_path = dev["path"]

    if best_path is None:
        logger.warning("detect_touch_device: no MT-capable touchscreen found on serial=%s", serial)
    return best_path


# Type name mapping: internal action → spec-compliant type string
_ACTION_MAP = {
    "DOWN": "touch_down",
    "MOVE": "touch_move",
    "UP": "touch_up",
}


class TouchEventMonitor:
    """Daemon thread that streams getevent output and queues RawTouchEvents.

    Usage::

        stop = threading.Event()
        monitor = TouchEventMonitor(adb=adb_connection, stop_event=stop)
        node = monitor.detect_touch_device()   # optional — auto-called in start()
        monitor.start()

        # Per tick:
        events = monitor.drain()

        # On shutdown:
        stop.set()
    """

    def __init__(
        self,
        adb: AdbConnection,
        stop_event: threading.Event,
        maxsize: int = 500,
    ) -> None:
        self._adb = adb
        self._stop_event = stop_event
        self._queue: queue.Queue[RawTouchEvent] = queue.Queue(maxsize=maxsize)
        self._thread: threading.Thread | None = None
        self._maxsize = maxsize

    # ─── Public API ───────────────────────────────────────────────────────────

    def start(self, node: str | None = None) -> None:
        """Detect the touchscreen node (if not provided) and launch the daemon thread.

        Raises:
            TouchDeviceNotFoundError: If no node is provided and auto-detection
                finds no touchscreen device on the connected ADB device.
        """
        if node is None:
            serial = getattr(self._adb, "_serial", None) or ""
            node = detect_touch_device(serial)
            if node is None:
                raise TouchDeviceNotFoundError(
                    f"No touchscreen detected on device {serial!r}. Cannot start event capture."
                )
        self._thread = threading.Thread(
            target=self._run,
            args=(node,),
            daemon=True,
            name="TouchEventMonitor",
        )
        self._thread.start()

    def drain(self) -> list[RawTouchEvent]:
        """Return all currently queued RawTouchEvents without blocking."""
        items: list[RawTouchEvent] = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def stop(self) -> None:
        """Signal the monitor to stop and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def detect_touch_device(self) -> str | None:
        """Auto-detect the touchscreen /dev/input/eventN node.

        Delegates to the module-level :func:`detect_touch_device` function
        using the serial from the underlying ADB connection.

        Returns:
            Device node string (e.g. ``"/dev/input/event8"``), or ``None``
            if no touchscreen device is found.
        """
        serial = getattr(self._adb, "_serial", None) or ""
        return detect_touch_device(serial)

    # ─── Internal thread ──────────────────────────────────────────────────────

    def _run(self, node: str) -> None:
        """Thread target: stream getevent output and parse into RawTouchEvents."""
        logger.info("TouchEventMonitor: starting event capture on node=%s", node)
        cmd = f"getevent -l -t {node}"
        event_count = 0
        try:
            for line in self._adb.shell_stream(cmd):
                if self._stop_event.is_set():
                    break
                # shell_stream may yield bytes or str depending on adbutils version
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                before = self._queue.qsize()
                self._parse_line(line)
                if self._queue.qsize() > before:
                    event_count += 1
        except Exception:
            logger.exception("TouchEventMonitor: stream error")
        logger.info("TouchEventMonitor: capture ended, %d events enqueued", event_count)

    # ─── getevent line parser (mini state machine) ───────────────────────────

    # Parser state (per-instance, only one thread accesses these)
    _current_ts: float = 0.0
    _current_slot: int = 0
    _current_x: int | None = None
    _current_y: int | None = None
    _current_action: str = "MOVE"
    _pending: bool = False  # True when we have unsent accumulated state

    def _parse_line(self, line: str) -> None:  # noqa: C901
        """Parse a single getevent line and enqueue a RawTouchEvent on SYN_REPORT."""
        m = _LINE_RE.search(line)
        if not m:
            return

        ts = float(m.group("ts"))
        ev_type = m.group("ev_type")
        ev_code = m.group("ev_code")
        value = int(m.group("value"), 16)

        if ev_type == "EV_ABS":
            if ev_code == "ABS_MT_SLOT":
                self._current_slot = value
            elif ev_code == "ABS_MT_TRACKING_ID":
                if value == _TRACKING_ID_INVALID:
                    # Contact lifted → emit UP on next SYN_REPORT
                    self._current_action = "UP"
                else:
                    # New contact → DOWN
                    self._current_action = "DOWN"
                    self._current_x = None
                    self._current_y = None
                self._current_ts = ts
                self._pending = True
            elif ev_code == "ABS_MT_POSITION_X":
                self._current_x = value
                self._current_ts = ts
                self._pending = True
            elif ev_code == "ABS_MT_POSITION_Y":
                self._current_y = value
                self._current_ts = ts
                self._pending = True

        elif ev_type == "EV_SYN" and ev_code == "SYN_REPORT":
            if self._pending:
                evt = RawTouchEvent(
                    ts=self._current_ts,
                    type=_ACTION_MAP.get(self._current_action, "touch_move"),
                    slot=self._current_slot,
                    x=self._current_x if self._current_x is not None else 0,
                    y=self._current_y if self._current_y is not None else 0,
                )
                try:
                    self._queue.put_nowait(evt)
                except queue.Full:
                    logger.warning(
                        "TouchEventMonitor: queue full (maxsize=%d) — dropping event",
                        self._maxsize,
                    )
                # Reset action to MOVE for the next SYN_REPORT cycle
                self._current_action = "MOVE"
                self._pending = False
