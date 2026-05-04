"""RED tests for EventPersister — Phase 1.1.

Tests the core happy path: drain events, write JSONL, format with 5-field whitelist.
GREEN implementation comes in Batch 1.2.
"""

from __future__ import annotations

import json
from pathlib import Path
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
