"""TouchEventMonitor — daemon thread that streams getevent and queues RawTouchEvents.

Adapted from the private trainer's recorder/event_monitor.py.
Changes:
- Import: gameplay_recorder.models.touch_event (not the private trainer models)
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
import threading
from typing import TYPE_CHECKING

from gameplay_recorder.models.touch_event import RawTouchEvent

if TYPE_CHECKING:
    from gameplay_recorder.adb.connection import AdbConnection

logger = logging.getLogger(__name__)

# ─── getevent line regex ──────────────────────────────────────────────────────

# Matches: "[<ts>] <dev>: EV_TYPE  EV_CODE  <hex_value>"
_LINE_RE = re.compile(
    r"\[\s*(?P<ts>[0-9.]+)\]\s+\S+:\s+(?P<ev_type>\S+)\s+(?P<ev_code>\S+)\s+(?P<value>[0-9a-fA-F]+)"
)

# Device node detection — matches the device path before the colon
_DEVICE_BLOCK_RE = re.compile(r"add device \d+:\s+(?P<node>/dev/input/\S+)")

_TRACKING_ID_INVALID = 0xFFFFFFFF  # getevent value for contact-lifted

_FALLBACK_NODE = "/dev/input/event3"

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
        """Detect the touchscreen node (if not provided) and launch the daemon thread."""
        if node is None:
            node = self.detect_touch_device()
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

    def detect_touch_device(self) -> str:
        """Auto-detect the touchscreen /dev/input/eventN node.

        Runs ``getevent -p``, searches for the device block that reports
        ABS_MT_POSITION_X, and returns that device path.

        Returns:
            Device node string (e.g. ``"/dev/input/event3"``).
            Falls back to ``_FALLBACK_NODE`` if not found.
        """
        try:
            output = self._adb.shell("getevent -p")
        except Exception:
            logger.warning("detect_touch_device: getevent -p failed, using fallback")
            return _FALLBACK_NODE

        current_node: str | None = None
        for line in output.splitlines():
            m = _DEVICE_BLOCK_RE.search(line)
            if m:
                current_node = m.group("node")
                continue
            if "ABS_MT_POSITION_X" in line and current_node is not None:
                return current_node

        logger.warning("detect_touch_device: no ABS_MT_POSITION_X found, using fallback")
        return _FALLBACK_NODE

    # ─── Internal thread ──────────────────────────────────────────────────────

    def _run(self, node: str) -> None:
        """Thread target: stream getevent output and parse into RawTouchEvents."""
        cmd = f"getevent -l -t {node}"
        try:
            for line in self._adb.shell_stream(cmd):
                if self._stop_event.is_set():
                    break
                # shell_stream may yield bytes or str depending on adbutils version
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                self._parse_line(line)
        except Exception:
            logger.exception("TouchEventMonitor: stream error")

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
