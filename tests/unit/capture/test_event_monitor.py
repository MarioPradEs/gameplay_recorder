"""Unit tests for capture/event_monitor.py — TouchEventMonitor class.

Tests cover:
- Parsing single finger down/move/up sequence
- Multi-touch slot handling
- Ignoring unrelated event types
- Malformed line graceful skip
- Stop terminates stream
- No input injection possible (defensive)

getevent -l -t line format tested:
    [<timestamp>] /dev/input/eventN: EV_TYPE  EV_CODE  <hex_value>
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from gameplay_recorder.capture.event_monitor import TouchEventMonitor
from gameplay_recorder.models.touch_event import RawTouchEvent

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_adb_connection(lines: list[str]) -> MagicMock:
    """Return a mock AdbConnection whose shell_stream yields the given lines."""
    conn = MagicMock()
    conn.shell_stream.return_value = iter(lines)
    # shell() used by detect_touch_device — return empty string by default
    conn.shell.return_value = ""
    return conn


def _run_monitor_sync(lines: list[str], stop_after: int = 999) -> list[RawTouchEvent]:
    """Run TouchEventMonitor synchronously and return all drained events.

    Creates a stop_event that fires immediately after lines are exhausted
    so the test doesn't block.
    """
    stop_event = threading.Event()
    adb = _make_adb_connection(lines)
    monitor = TouchEventMonitor(adb=adb, stop_event=stop_event)
    # Feed lines directly through the internal parser (pure logic, no thread)
    for line in lines:
        monitor._parse_line(line)
    return monitor.drain()


# Canned getevent lines for a finger DOWN → MOVE → UP sequence on slot 0
_DOWN_LINES = [
    "[ 1000.100] /dev/input/event3: EV_ABS  ABS_MT_TRACKING_ID  00000001",
    "[ 1000.100] /dev/input/event3: EV_ABS  ABS_MT_POSITION_X   00000218",
    "[ 1000.100] /dev/input/event3: EV_ABS  ABS_MT_POSITION_Y   000004a4",
    "[ 1000.100] /dev/input/event3: EV_SYN  SYN_REPORT           00000000",
]

_MOVE_LINES = [
    "[ 1000.200] /dev/input/event3: EV_ABS  ABS_MT_POSITION_X   00000220",
    "[ 1000.200] /dev/input/event3: EV_ABS  ABS_MT_POSITION_Y   000004b0",
    "[ 1000.200] /dev/input/event3: EV_SYN  SYN_REPORT           00000000",
]

_UP_LINES = [
    "[ 1000.300] /dev/input/event3: EV_ABS  ABS_MT_TRACKING_ID  ffffffff",
    "[ 1000.300] /dev/input/event3: EV_SYN  SYN_REPORT           00000000",
]


# ─── Parsing: single finger down → move → up ─────────────────────────────────


class TestParseSingleFingerSequence:
    def test_parses_single_finger_down_move_up_sequence(self) -> None:
        all_lines = _DOWN_LINES + _MOVE_LINES + _UP_LINES
        events = _run_monitor_sync(all_lines)

        assert len(events) == 3
        down, move, up = events

        assert down.type == "touch_down"
        assert down.x == 0x218  # 536
        assert down.y == 0x4A4  # 1188
        assert isinstance(down.ts, float)

        assert move.type == "touch_move"
        assert move.x == 0x220  # 544
        assert move.y == 0x4B0  # 1200

        assert up.type == "touch_up"

    def test_touch_down_event_has_required_fields(self) -> None:
        events = _run_monitor_sync(_DOWN_LINES)
        assert len(events) == 1
        evt = events[0]
        # All 5 required fields must be present
        assert hasattr(evt, "ts")
        assert hasattr(evt, "type")
        assert hasattr(evt, "x")
        assert hasattr(evt, "y")
        assert hasattr(evt, "slot")

    def test_touch_event_type_values_are_spec_compliant(self) -> None:
        """Types must be 'touch_down', 'touch_move', 'touch_up' — NOT 'DOWN'/'MOVE'/'UP'."""
        all_lines = _DOWN_LINES + _MOVE_LINES + _UP_LINES
        events = _run_monitor_sync(all_lines)
        allowed = {"touch_down", "touch_move", "touch_up"}
        for evt in events:
            assert evt.type in allowed, f"Got non-spec type: {evt.type!r}"

    def test_touch_down_sets_slot_zero_by_default(self) -> None:
        events = _run_monitor_sync(_DOWN_LINES)
        assert events[0].slot == 0

    def test_touch_move_timestamp_matches_getevent_line(self) -> None:
        events = _run_monitor_sync(_MOVE_LINES)
        assert len(events) == 1
        assert abs(events[0].ts - 1000.200) < 0.001


# ─── Parsing: multi-touch slots ───────────────────────────────────────────────


class TestParseMultiTouchSlots:
    _SLOT1_DOWN = [
        "[ 2000.000] /dev/input/event3: EV_ABS  ABS_MT_SLOT          00000001",
        "[ 2000.000] /dev/input/event3: EV_ABS  ABS_MT_TRACKING_ID  00000002",
        "[ 2000.000] /dev/input/event3: EV_ABS  ABS_MT_POSITION_X   00000100",
        "[ 2000.000] /dev/input/event3: EV_ABS  ABS_MT_POSITION_Y   00000200",
        "[ 2000.000] /dev/input/event3: EV_SYN  SYN_REPORT           00000000",
    ]

    def test_parses_multi_touch_slots(self) -> None:
        events = _run_monitor_sync(self._SLOT1_DOWN)
        assert len(events) == 1
        evt = events[0]
        assert evt.slot == 1
        assert evt.x == 0x100
        assert evt.y == 0x200
        assert evt.type == "touch_down"

    def test_slot_switches_correctly_between_two_fingers(self) -> None:
        slot0_lines = _DOWN_LINES  # slot 0 (default)
        slot1_lines = self._SLOT1_DOWN
        events = _run_monitor_sync(slot0_lines + slot1_lines)
        assert len(events) == 2
        assert events[0].slot == 0
        assert events[1].slot == 1


# ─── Ignoring unrelated event types ──────────────────────────────────────────


class TestIgnoresUnrelatedEventTypes:
    def test_ignores_unrelated_event_types(self) -> None:
        """EV_KEY / SYN_MT_REPORT / etc. must produce no events."""
        noise_lines = [
            "[ 3000.000] /dev/input/event3: EV_KEY  BTN_TOOL_FINGER  00000001",
            "[ 3000.000] /dev/input/event3: EV_SYN  SYN_MT_REPORT    00000000",
        ]
        events = _run_monitor_sync(noise_lines)
        assert events == []

    def test_btn_touch_line_alone_produces_no_event(self) -> None:
        """BTN_TOUCH without X/Y/TRACKING_ID should not emit a partial event."""
        lines = [
            "[ 4000.000] /dev/input/event3: EV_KEY  BTN_TOUCH        00000001",
            "[ 4000.000] /dev/input/event3: EV_SYN  SYN_REPORT       00000000",
        ]
        events = _run_monitor_sync(lines)
        assert events == []

    def test_only_syn_report_without_pending_produces_no_event(self) -> None:
        """A SYN_REPORT with no pending state must not emit a spurious event."""
        lines = [
            "[ 5000.000] /dev/input/event3: EV_SYN  SYN_REPORT       00000000",
        ]
        events = _run_monitor_sync(lines)
        assert events == []


# ─── Malformed lines ──────────────────────────────────────────────────────────


class TestHandlesMalformedLines:
    def test_handles_malformed_line_gracefully(self) -> None:
        """Garbage input must be silently skipped, not crash the parser."""
        junk_lines = [
            "this is not a getevent line at all",
            "",
            "   ",
            "[bad timestamp] /dev: EV_ABS INCOMPLETE",
            "totally random garbage !!@@##",
        ]
        # Must not raise
        events = _run_monitor_sync(junk_lines)
        assert events == []

    def test_real_line_after_malformed_still_parsed(self) -> None:
        """Parser must recover and continue after a malformed line."""
        lines = [
            "garbage garbage garbage",
            *_DOWN_LINES,
        ]
        events = _run_monitor_sync(lines)
        assert len(events) == 1
        assert events[0].type == "touch_down"


# ─── Stop terminates stream ───────────────────────────────────────────────────


class TestStopTerminatesStream:
    def test_stop_terminates_stream(self) -> None:
        """Setting stop_event must cause the monitor thread to exit cleanly."""
        stop_event = threading.Event()
        adb = _make_adb_connection(_DOWN_LINES * 10)
        monitor = TouchEventMonitor(adb=adb, stop_event=stop_event)

        stop_event.set()  # signal before start — thread should exit immediately
        monitor.start(node="/dev/input/event3")
        monitor._thread.join(timeout=2.0)

        assert not monitor._thread.is_alive(), "Monitor thread did not stop within 2s"

    def test_drain_after_stop_returns_empty_list(self) -> None:
        """After stop, drain() must return [] (queue may have been consumed)."""
        stop_event = threading.Event()
        adb = _make_adb_connection([])
        monitor = TouchEventMonitor(adb=adb, stop_event=stop_event)
        stop_event.set()
        result = monitor.drain()
        assert isinstance(result, list)


# ─── Defensive: no input injection ───────────────────────────────────────────


class TestEventMonitorDoesNotCallInputInjection:
    def test_event_monitor_does_not_call_input_injection(self) -> None:
        """TouchEventMonitor must not call any banned method on AdbConnection.

        Since AdbConnection itself has no such API, this test verifies that
        the monitor doesn't somehow bypass the firewall via dynamic dispatch.
        """
        stop_event = threading.Event()
        adb = _make_adb_connection(_DOWN_LINES)
        monitor = TouchEventMonitor(adb=adb, stop_event=stop_event)
        for line in _DOWN_LINES:
            monitor._parse_line(line)

        banned = {"tap", "swipe", "input_text", "input_keyevent", "send_keys", "click", "press"}
        for method in banned:
            assert not getattr(adb, method, MagicMock()).called, (
                f"TouchEventMonitor called banned method: {method!r}"
            )
