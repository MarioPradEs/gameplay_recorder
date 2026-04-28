"""Tests for SessionMeta and RecordingState — RED phase.

Spec: Requirement "Session Metadata", Requirement "GUI State Machine"
"""

import dataclasses
import re

import pytest

from gameplay_recorder.models.session import RecordingState, SessionMeta


# ---------------------------------------------------------------------------
# SessionMeta
# ---------------------------------------------------------------------------

VALID_META = dict(
    game_id="zombie_gore",
    game_version="1.32.1",
    recorded_by="alice",
    started_at="2026-04-28T14:00:00Z",
    duration_seconds=120,
    schema_version="1",
)


class TestSessionMetaStructure:
    """SessionMeta must have exactly 6 fields — no extras, no omissions."""

    def test_session_meta_is_dataclass(self):
        assert dataclasses.is_dataclass(SessionMeta)

    def test_session_meta_fields_exact(self):
        """Spec: Requirement 'Session Metadata' — exactly 6 fields."""
        expected = {
            "game_id",
            "game_version",
            "recorded_by",
            "started_at",
            "duration_seconds",
            "schema_version",
        }
        actual = {f.name for f in dataclasses.fields(SessionMeta)}
        assert actual == expected, (
            f"Field mismatch: extra={actual - expected!r}, missing={expected - actual!r}"
        )

    def test_session_meta_field_count(self):
        """Ensure count is 6 — redundant but explicit guard."""
        assert len(dataclasses.fields(SessionMeta)) == 6


class TestSessionMetaFieldValues:
    """Round-trip: every field stores what we pass in."""

    def test_game_id_stored(self):
        meta = SessionMeta(**VALID_META)
        assert meta.game_id == "zombie_gore"

    def test_game_version_stored(self):
        meta = SessionMeta(**VALID_META)
        assert meta.game_version == "1.32.1"

    def test_recorded_by_stored(self):
        meta = SessionMeta(**VALID_META)
        assert meta.recorded_by == "alice"

    def test_started_at_stored(self):
        meta = SessionMeta(**VALID_META)
        assert meta.started_at == "2026-04-28T14:00:00Z"

    def test_duration_seconds_stored(self):
        meta = SessionMeta(**VALID_META)
        assert meta.duration_seconds == 120

    def test_schema_version_stored_as_string(self):
        """spec: schema_version is the string literal "1", not int 1."""
        meta = SessionMeta(**VALID_META)
        assert meta.schema_version == "1"
        assert isinstance(meta.schema_version, str), "schema_version must be a string, not int"

    def test_schema_version_not_int(self):
        meta = SessionMeta(**VALID_META)
        assert meta.schema_version != 1, "schema_version must be string '1', not int 1"


class TestSessionMetaStartedAtFormat:
    """started_at must match UTC ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ."""

    UTC_ISO8601_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_started_at_utc_iso8601_pattern(self):
        meta = SessionMeta(**VALID_META)
        assert self.UTC_ISO8601_PATTERN.match(meta.started_at), (
            f"started_at={meta.started_at!r} does not match YYYY-MM-DDTHH:MM:SSZ"
        )

    def test_started_at_utc_iso8601_alternate_time(self):
        """Triangulation: different timestamp, same pattern requirement."""
        meta = SessionMeta(
            game_id="game_x",
            game_version="2.0",
            recorded_by="bob",
            started_at="2025-12-31T23:59:59Z",
            duration_seconds=60,
            schema_version="1",
        )
        assert self.UTC_ISO8601_PATTERN.match(meta.started_at)


class TestSessionMetaImmutability:
    def test_session_meta_is_frozen(self):
        meta = SessionMeta(**VALID_META)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            meta.game_id = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RecordingState
# ---------------------------------------------------------------------------


class TestRecordingStateEnum:
    """Spec: Requirement 'GUI State Machine' — 4 states: IDLE, RECORDING, PACKAGING, DONE."""

    def test_idle_member_exists(self):
        assert hasattr(RecordingState, "IDLE")

    def test_recording_member_exists(self):
        assert hasattr(RecordingState, "RECORDING")

    def test_packaging_member_exists(self):
        assert hasattr(RecordingState, "PACKAGING")

    def test_done_member_exists(self):
        assert hasattr(RecordingState, "DONE")

    def test_exactly_four_members(self):
        """No extra states beyond the spec's 4."""
        assert len(RecordingState) == 4

    def test_all_required_members(self):
        """Triangulation: check all four names at once."""
        names = {s.name for s in RecordingState}
        assert names == {"IDLE", "RECORDING", "PACKAGING", "DONE"}
