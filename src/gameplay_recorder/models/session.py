"""Domain models: session metadata and recording state machine.

SessionMeta holds the 6 required fields for session_meta.json.
RecordingState is the 4-value enum driving the GUI state machine.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SessionMeta:
    """Metadata for a completed recording session.

    Serialised to session_meta.json inside the output ZIP.
    Exactly 6 fields — no extras (spec: Requirement "Session Metadata").

    Fields:
        game_id:          Identifier string from the game dropdown (e.g. "zombie_gore").
        game_version:     Free-text game version string (e.g. "1.32.1").
        recorded_by:      Player / operator name.
        started_at:       UTC ISO 8601 timestamp string (YYYY-MM-DDTHH:MM:SSZ).
        duration_seconds: Wall-clock duration of the session in whole seconds.
        schema_version:   String literal "1" — must NOT be integer 1.
    """

    game_id: str
    game_version: str
    recorded_by: str
    started_at: str  # UTC ISO 8601: YYYY-MM-DDTHH:MM:SSZ
    duration_seconds: int
    schema_version: str = field(default="1")


class RecordingState(enum.Enum):
    """States for the GUI state machine.

    Spec: Requirement "GUI State Machine" — exactly 4 states.
    Transitions: IDLE -> RECORDING -> PACKAGING -> DONE -> IDLE.
    """

    IDLE = "idle"
    RECORDING = "recording"
    PACKAGING = "packaging"
    DONE = "done"
