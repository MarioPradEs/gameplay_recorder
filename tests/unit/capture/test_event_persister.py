"""RED tests for EventPersister — Phase 1.1.

Tests the core happy path: drain events, write JSONL, format with 5-field whitelist.
GREEN implementation comes in Batch 1.2.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from gameplay_recorder.models.touch_event import RawTouchEvent


@pytest.fixture
def qapp():
    """Provide a QApplication for QThread-based tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _make_event(
    ts: float = 1.0, type_: str = "touch_down", x: int = 100, y: int = 200, slot: int = 0
) -> RawTouchEvent:
    """Build a RawTouchEvent matching the 5-field whitelist."""
    return RawTouchEvent(ts=ts, type=type_, x=x, y=y, slot=slot)


def test_event_persister_writes_drained_events_as_jsonl_lines(qapp, tmp_path):
    """EventPersister.run() drains the monitor and writes one JSON line per event."""
    from gameplay_recorder.capture.event_persister import EventPersister

    events = [
        _make_event(ts=1.0, type_="touch_down", x=10, y=20, slot=0),
        _make_event(ts=1.1, type_="touch_move", x=15, y=25, slot=0),
        _make_event(ts=1.2, type_="touch_up", x=20, y=30, slot=0),
    ]
    drain_calls = [events, []]  # First drain returns 3 events, then empty
    monitor = MagicMock()
    monitor.drain = MagicMock(side_effect=lambda: drain_calls.pop(0) if drain_calls else [])

    output = tmp_path / "events.jsonl"
    persister = EventPersister(monitor=monitor, output_path=output, drain_interval_ms=50)
    persister.start()

    # Let it drain at least twice, then interrupt
    qapp.processEvents()
    persister.msleep(200)
    persister.requestInterruption()
    finished = persister.wait(2000)
    assert finished, "EventPersister did not exit within 2s"

    assert output.exists()
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert parsed[0] == {"ts": 1.0, "type": "touch_down", "x": 10, "y": 20, "slot": 0}
    assert parsed[1] == {"ts": 1.1, "type": "touch_move", "x": 15, "y": 25, "slot": 0}
    assert parsed[2] == {"ts": 1.2, "type": "touch_up", "x": 20, "y": 30, "slot": 0}


def test_event_persister_format_event_produces_5_field_whitelist_only(qapp, tmp_path):
    """_format_event must produce JSON with EXACTLY ts, type, x, y, slot — no other fields."""
    from gameplay_recorder.capture.event_persister import EventPersister

    output = tmp_path / "events.jsonl"
    monitor = MagicMock()
    monitor.drain = MagicMock(return_value=[])
    persister = EventPersister(monitor=monitor, output_path=output)

    ev = _make_event(ts=42.5, type_="touch_down", x=300, y=400, slot=1)
    formatted = persister._format_event(ev)
    parsed = json.loads(formatted)

    assert set(parsed.keys()) == {"ts", "type", "x", "y", "slot"}, (
        f"Extra or missing fields in serialized event: {set(parsed.keys())}"
    )
    assert parsed["ts"] == 42.5
    assert parsed["type"] == "touch_down"
    assert parsed["x"] == 300
    assert parsed["y"] == 400
    assert parsed["slot"] == 1


def test_event_persister_creates_empty_file_when_no_events_drained(qapp, tmp_path):
    """Even with zero events, run() should leave events.jsonl on disk (empty)."""
    from gameplay_recorder.capture.event_persister import EventPersister

    output = tmp_path / "events.jsonl"
    monitor = MagicMock()
    monitor.drain = MagicMock(return_value=[])

    persister = EventPersister(monitor=monitor, output_path=output, drain_interval_ms=50)
    persister.start()
    persister.msleep(150)
    persister.requestInterruption()
    finished = persister.wait(2000)
    assert finished, "EventPersister did not exit within 2s"

    assert output.exists(), "events.jsonl must exist even with no events drained"
    assert output.read_text(encoding="utf-8") == ""


def test_event_persister_exits_within_500ms_of_interruption_request(qapp, tmp_path):
    """REQ-EP-4: requestInterruption() causes run() to exit within 500ms."""
    import time

    from gameplay_recorder.capture.event_persister import EventPersister

    output = tmp_path / "events.jsonl"
    monitor = MagicMock()
    monitor.drain = MagicMock(return_value=[])
    persister = EventPersister(monitor=monitor, output_path=output, drain_interval_ms=250)

    persister.start()
    persister.msleep(50)  # Let it enter the loop
    t0 = time.monotonic()
    persister.requestInterruption()
    finished = persister.wait(500)  # MUST exit within 500ms
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert finished, f"EventPersister did not exit within 500ms (elapsed={elapsed_ms:.0f}ms)"
    assert elapsed_ms < 500, f"REQ-EP-4 violated — exit took {elapsed_ms:.0f}ms"


def test_event_persister_emits_finished_clean_with_total_count(qapp, tmp_path):
    """REQ-EP-9 / design §2: emits finished_clean(total_count: int) when run() exits."""
    from gameplay_recorder.capture.event_persister import EventPersister

    events_batch_1 = [_make_event(ts=1.0), _make_event(ts=1.1)]
    events_batch_2 = [_make_event(ts=1.2)]
    drain_calls = [events_batch_1, events_batch_2, []]
    monitor = MagicMock()
    monitor.drain = MagicMock(side_effect=lambda: drain_calls.pop(0) if drain_calls else [])

    output = tmp_path / "events.jsonl"
    persister = EventPersister(monitor=monitor, output_path=output, drain_interval_ms=50)

    received: list[int] = []
    persister.finished_clean.connect(lambda total: received.append(total))

    persister.start()
    persister.msleep(250)  # Let it run a few drains
    persister.requestInterruption()
    persister.wait(2000)
    qapp.processEvents()  # Flush queued signal delivery

    assert received, "finished_clean was not emitted"
    assert received[0] == 3, f"Expected total=3, got {received[0]}"


def test_event_persister_emits_error_signal_on_io_failure(qapp, tmp_path):
    """REQ-EP-9 / Scenario 5: I/O error during write emits error(str), does not crash."""
    from gameplay_recorder.capture.event_persister import EventPersister

    # Point output_path at a directory (not a file) → open("a") will OSError on Windows.
    bad_dir = tmp_path / "not_a_file"
    bad_dir.mkdir()

    monitor = MagicMock()
    monitor.drain = MagicMock(return_value=[])
    persister = EventPersister(monitor=monitor, output_path=bad_dir, drain_interval_ms=50)

    received_errors: list[str] = []
    persister.error.connect(lambda msg: received_errors.append(msg))

    persister.start()
    persister.msleep(150)
    persister.requestInterruption()
    persister.wait(2000)
    qapp.processEvents()

    assert received_errors, "error signal not emitted on I/O failure"
    assert isinstance(received_errors[0], str)
    assert len(received_errors[0]) > 0


def test_event_persister_final_drain_after_interruption_captures_late_events(qapp, tmp_path):
    """REQ-EP-3: events arriving between last in-loop drain and exit must still land on disk.

    Simulates a touch event being enqueued AFTER requestInterruption() was called
    but BEFORE the run loop's exit. The persister must do a final drain on exit.
    """
    import json

    from gameplay_recorder.capture.event_persister import EventPersister

    interruption_requested = [False]
    late_event = _make_event(ts=99.0, type_="touch_up", x=500, y=500, slot=0)

    def drain_side_effect():
        # During the loop, return empty. AFTER interruption is requested, return the
        # late event exactly once on the next drain call.
        if interruption_requested[0]:
            interruption_requested[0] = False  # consume so we only return once
            return [late_event]
        return []

    monitor = MagicMock()
    monitor.drain = MagicMock(side_effect=drain_side_effect)

    output = tmp_path / "events.jsonl"
    persister = EventPersister(monitor=monitor, output_path=output, drain_interval_ms=50)

    persister.start()
    persister.msleep(150)  # A few empty drains in-loop
    interruption_requested[0] = True
    persister.requestInterruption()
    persister.wait(2000)

    assert output.exists()
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"Final drain missed the late event. lines={lines}"
    parsed = json.loads(lines[0])
    assert parsed["ts"] == 99.0
    assert parsed["type"] == "touch_up"
