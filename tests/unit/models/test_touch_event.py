"""Tests for RawTouchEvent dataclass — RED phase.

Spec: Requirement "Raw Touch Event Capture"
  - Each event: ts (float), type (str in {touch_down, touch_move, touch_up}),
    x (int), y (int), slot (int).
  - No additional fields.
"""

import dataclasses

import pytest

from gameplay_recorder.models.touch_event import RawTouchEvent


class TestRawTouchEventStructure:
    """Structural tests: dataclass identity and required fields."""

    def test_touch_event_is_dataclass(self):
        assert dataclasses.is_dataclass(RawTouchEvent)

    def test_touch_event_has_ts_field(self):
        event = RawTouchEvent(ts=1.5, type="touch_down", x=100, y=200, slot=0)
        assert event.ts == 1.5

    def test_touch_event_has_type_field(self):
        event = RawTouchEvent(ts=1.5, type="touch_move", x=50, y=75, slot=0)
        assert event.type == "touch_move"

    def test_touch_event_has_x_field(self):
        event = RawTouchEvent(ts=0.0, type="touch_down", x=320, y=0, slot=0)
        assert event.x == 320

    def test_touch_event_has_y_field(self):
        event = RawTouchEvent(ts=0.0, type="touch_up", x=0, y=480, slot=0)
        assert event.y == 480

    def test_touch_event_has_slot_field(self):
        event = RawTouchEvent(ts=0.0, type="touch_down", x=0, y=0, slot=1)
        assert event.slot == 1


class TestRawTouchEventFieldTypes:
    """Field type contracts."""

    def test_ts_is_float(self):
        event = RawTouchEvent(ts=3.14, type="touch_down", x=0, y=0, slot=0)
        assert isinstance(event.ts, float)

    def test_x_is_int(self):
        event = RawTouchEvent(ts=1.0, type="touch_move", x=100, y=200, slot=0)
        assert isinstance(event.x, int)

    def test_y_is_int(self):
        event = RawTouchEvent(ts=1.0, type="touch_move", x=100, y=200, slot=0)
        assert isinstance(event.y, int)

    def test_slot_is_int(self):
        event = RawTouchEvent(ts=1.0, type="touch_down", x=0, y=0, slot=2)
        assert isinstance(event.slot, int)


class TestRawTouchEventImmutability:
    """Frozen dataclass contract."""

    def test_touch_event_is_frozen(self):
        """Assigning to a frozen dataclass raises FrozenInstanceError."""
        event = RawTouchEvent(ts=1.0, type="touch_down", x=10, y=20, slot=0)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            event.x = 999  # type: ignore[misc]


class TestRawTouchEventEventTypes:
    """All three event types are accepted."""

    def test_touch_down_type_accepted(self):
        event = RawTouchEvent(ts=0.0, type="touch_down", x=0, y=0, slot=0)
        assert event.type == "touch_down"

    def test_touch_move_type_accepted(self):
        event = RawTouchEvent(ts=0.0, type="touch_move", x=0, y=0, slot=0)
        assert event.type == "touch_move"

    def test_touch_up_type_accepted(self):
        event = RawTouchEvent(ts=0.0, type="touch_up", x=0, y=0, slot=0)
        assert event.type == "touch_up"


class TestRawTouchEventExactFields:
    """Only the 5 allowed fields exist (IP-clean contract)."""

    def test_only_allowed_fields_exist(self):
        """The dataclass must have exactly: ts, type, x, y, slot.

        This test enforces the IP-isolation contract: no ML fields.
        """
        allowed = {"ts", "type", "x", "y", "slot"}
        actual = {f.name for f in dataclasses.fields(RawTouchEvent)}
        assert actual == allowed, (
            f"Unexpected fields: {actual - allowed!r}; missing: {allowed - actual!r}"
        )
