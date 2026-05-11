"""Unit tests for capture/event_monitor.py — TouchEventMonitor class.

Tests cover:
- Parsing single finger down/move/up sequence
- Multi-touch slot handling
- Ignoring unrelated event types
- Malformed line graceful skip
- Stop terminates stream
- No input injection possible (defensive)
- detect_touch_device module-level function (scoring heuristic, -lp flag, None return)

getevent -l -t line format tested:
    [<timestamp>] /dev/input/eventN: EV_TYPE  EV_CODE  <hex_value>
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from gameplay_recorder.adb.connection import AdbConnection
from gameplay_recorder.capture.event_monitor import TouchEventMonitor, detect_touch_device
from gameplay_recorder.models.touch_event import RawTouchEvent

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_adb_connection(lines: list[str]) -> MagicMock:
    """Return a spec=AdbConnection mock whose shell_stream yields the given lines.

    Using MagicMock(spec=AdbConnection) ensures that any call to a method that
    does NOT exist on AdbConnection raises AttributeError immediately — catching
    API drift (e.g. if event_monitor tried to call a non-existent method).
    """
    conn = MagicMock(spec=AdbConnection)
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
        """After stop, drain() must return [] (queue may have been consumed).

        Strengthened from type-only check (isinstance) to full-state assertion:
        - result must be exactly [] (not just any list)
        - result must be a list (type guard)
        - _thread must still be None (start() was never called)
        """
        stop_event = threading.Event()
        adb = _make_adb_connection([])
        monitor = TouchEventMonitor(adb=adb, stop_event=stop_event)
        stop_event.set()
        result = monitor.drain()
        assert result == [], f"Expected empty list, got {result!r}"
        assert isinstance(result, list), f"Expected list, got {type(result).__name__}"
        assert monitor._thread is None, "Thread should be None — start() was never called"


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


# ─── detect_touch_device (module-level function, scoring heuristic) ──────────


class TestDetectTouchDevice:
    def test_detect_touch_device_uses_lp_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confirm the adb invocation uses -lp, not -p."""
        captured: dict = {}

        def fake_run(cmd, *args, **kwargs):  # noqa: ANN001
            captured["cmd"] = cmd
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        monkeypatch.setattr("gameplay_recorder.capture.event_monitor.subprocess.run", fake_run)
        detect_touch_device("17d4994b")
        cmd = captured["cmd"]
        # cmd is a list like ["adb", "-s", "17d4994b", "shell", "getevent", "-lp"]
        assert "-lp" in cmd
        assert "-p" not in [c for c in cmd if c != "-lp"]  # not the bare -p

    def test_detect_touch_device_returns_none_when_no_touchscreen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no device has ABS_MT_POSITION_X+Y, return None (no silent fallback)."""
        fake_output = """add device 1: /dev/input/event0
  name:     "PowerKey"
  events:
    KEY (0001): KEY_POWER             KEY_VOLUMEUP
"""
        monkeypatch.setattr(
            "gameplay_recorder.capture.event_monitor.subprocess.run",
            lambda *a, **kw: MagicMock(stdout=fake_output, returncode=0),
        )
        result = detect_touch_device("17d4994b")
        assert result is None

    def test_detect_touch_device_picks_mt_capable_device(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single MT-capable device is returned."""
        fake_output = """add device 1: /dev/input/event0
  name:     "PowerKey"
  events:
    KEY (0001): KEY_POWER

add device 2: /dev/input/event8
  name:     "touchpanel"
  events:
    ABS (0003): ABS_MT_POSITION_X     ABS_MT_POSITION_Y
                ABS_MT_TRACKING_ID
  input props:
    INPUT_PROP_DIRECT
"""
        monkeypatch.setattr(
            "gameplay_recorder.capture.event_monitor.subprocess.run",
            lambda *a, **kw: MagicMock(stdout=fake_output, returncode=0),
        )
        result = detect_touch_device("17d4994b")
        assert result == "/dev/input/event8"

    def test_detect_touch_device_picks_highest_score_when_multiple_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When multiple MT-capable devices exist, picks the one with highest score."""
        fake_output = """add device 1: /dev/input/event5
  name:     "secondary_mt"
  events:
    ABS (0003): ABS_MT_POSITION_X     ABS_MT_POSITION_Y

add device 2: /dev/input/event8
  name:     "touchpanel"
  events:
    ABS (0003): ABS_MT_POSITION_X     ABS_MT_POSITION_Y
                ABS_MT_TRACKING_ID
  input props:
    INPUT_PROP_DIRECT
"""
        monkeypatch.setattr(
            "gameplay_recorder.capture.event_monitor.subprocess.run",
            lambda *a, **kw: MagicMock(stdout=fake_output, returncode=0),
        )
        result = detect_touch_device("17d4994b")
        # event8: +10+10+5+5+2 = 32, event5: +10+10 = 20
        assert result == "/dev/input/event8"

    def test_detect_touch_device_threshold_requires_both_x_and_y(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A device with only ABS_MT_POSITION_X (no Y) must NOT be a candidate."""
        fake_output = """add device 1: /dev/input/event5
  name:     "incomplete_mt"
  events:
    ABS (0003): ABS_MT_POSITION_X
"""
        monkeypatch.setattr(
            "gameplay_recorder.capture.event_monitor.subprocess.run",
            lambda *a, **kw: MagicMock(stdout=fake_output, returncode=0),
        )
        result = detect_touch_device("17d4994b")
        assert result is None

    def test_detect_touch_device_raises_on_subprocess_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When subprocess.run raises, detect_touch_device returns None gracefully."""
        monkeypatch.setattr(
            "gameplay_recorder.capture.event_monitor.subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("adb not found")),
        )
        result = detect_touch_device("17d4994b")
        assert result is None


class TestTouchEventMonitorRaisesOnNoDevice:
    def test_start_raises_when_detect_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TouchEventMonitor.start() with no node and None detection raises TouchDeviceNotFoundError."""
        from gameplay_recorder.capture.event_monitor import TouchDeviceNotFoundError

        monkeypatch.setattr(
            "gameplay_recorder.capture.event_monitor.detect_touch_device",
            lambda serial: None,
        )
        stop_event = threading.Event()
        adb = MagicMock(spec=AdbConnection)
        adb._serial = "17d4994b"
        monitor = TouchEventMonitor(adb=adb, stop_event=stop_event)
        with pytest.raises(TouchDeviceNotFoundError):
            monitor.start()  # no node= provided → triggers auto-detect → None → raises


# ─── Phase 4.7: single-device getevent format (no <device>: prefix) ──────────


class TestParseLineSingleDeviceFormat:
    """getevent -l -t <single_node> omits the device prefix in each line.

    Empirical evidence: running
        adb shell getevent -lt /dev/input/event8
    on OnePlus CPH2581 yields lines like:
        [   17087.022366] EV_ABS       ABS_MT_POSITION_X    00004019
    with NO /dev/input/eventN: prefix. The old regex required the prefix as
    mandatory → 100% parse failure → 0 events enqueued → events.jsonl empty.
    """

    def test_parse_line_handles_single_device_format_without_prefix(self) -> None:
        """_LINE_RE must match a getevent line with NO <device>: prefix.

        Empirical fixture taken from real device output:
          adb shell getevent -lt /dev/input/event8  (OnePlus CPH2581)
        """
        from gameplay_recorder.capture.event_monitor import _LINE_RE

        line = "[   17087.022366] EV_ABS       ABS_MT_POSITION_X    00004019"
        m = _LINE_RE.search(line)
        assert m is not None, (
            "Regex must match single-device getevent format (no <device>: prefix). "
            f"Line was: {line!r}"
        )
        assert m.group("ev_type") == "EV_ABS"
        assert m.group("ev_code") == "ABS_MT_POSITION_X"
        assert m.group("value") == "00004019"

    def test_full_touch_sequence_single_device_format_enqueues_event(self) -> None:
        """A 4-line DOWN tap without prefix must enqueue at least one RawTouchEvent."""
        lines = [
            "[   17087.022366] EV_ABS       ABS_MT_TRACKING_ID   00000010",
            "[   17087.022366] EV_ABS       ABS_MT_POSITION_X    00004019",
            "[   17087.022366] EV_ABS       ABS_MT_POSITION_Y    0000774f",
            "[   17087.022366] EV_SYN       SYN_REPORT           00000000",
        ]
        events = _run_monitor_sync(lines)
        assert len(events) >= 1, (
            f"Expected at least 1 RawTouchEvent from single-device format, "
            f"got {len(events)}: {events}"
        )

    def test_parse_line_still_matches_multi_device_format_with_prefix(self) -> None:
        """Backward-compat: the regex must ALSO match multi-device format WITH prefix."""
        from gameplay_recorder.capture.event_monitor import _LINE_RE

        line = "[   17087.022366] /dev/input/event8: EV_ABS       ABS_MT_POSITION_X    00004019"
        m = _LINE_RE.search(line)
        assert m is not None, (
            "Regex must still match multi-device format (with <device>: prefix). "
            f"Line was: {line!r}"
        )
        assert m.group("ev_type") == "EV_ABS"
        assert m.group("ev_code") == "ABS_MT_POSITION_X"
        assert m.group("value") == "00004019"
