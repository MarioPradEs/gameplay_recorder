"""Domain model: a single raw touch event from the kernel input subsystem.

Each instance represents one parsed event from `adb shell getevent -l -t`.
Only the 5 public fields are kept — no ML/consumer-system-specific fields.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RawTouchEvent:
    """A single parsed touch event from the kernel input subsystem.

    Fields:
        ts:    Unix epoch timestamp in seconds (float, from getevent -t).
        type:  Logical phase: "touch_down", "touch_move", or "touch_up".
        x:     ABS_MT_POSITION_X pixel coordinate (int).
        y:     ABS_MT_POSITION_Y pixel coordinate (int).
        slot:  ABS_MT_SLOT finger index (0 for the first/only finger).
    """

    ts: float
    type: str  # "touch_down" | "touch_move" | "touch_up"
    x: int
    y: int
    slot: int = 0
