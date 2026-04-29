"""Tests for gameplay_recorder.packaging.metadata.

Phase 7: Packaging / Metadata — Strict TDD (RED first).
Spec: Requirement "Session Metadata".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from gameplay_recorder.models.session import SessionMeta


def _make_meta(**overrides) -> SessionMeta:
    """Helper: build a valid SessionMeta, optionally overriding fields."""
    defaults = dict(
        game_id="my_game",
        game_version="1.32.1",
        recorded_by="alice",
        started_at="2026-04-28T14:00:00Z",
        duration_seconds=42,
        schema_version="1",
    )
    defaults.update(overrides)
    return SessionMeta(**defaults)


class TestSerializeMeta:
    """Tests for serialize_meta() — pure dict serialization."""

    def test_session_meta_serializes_all_6_fields(self) -> None:
        """serialize_meta returns a dict with exactly 6 keys.

        Spec: Requirement "Session Metadata", Scenario "Metadata file contents".
        """
        from gameplay_recorder.packaging.metadata import serialize_meta

        meta = _make_meta()
        result = serialize_meta(meta)

        assert len(result) == 6

    def test_session_meta_no_extra_fields(self) -> None:
        """serialize_meta returns ONLY the 6 allowed keys — no extras.

        Spec: Requirement "Session Metadata", Scenario "Metadata file contents".
        """
        from gameplay_recorder.packaging.metadata import serialize_meta

        meta = _make_meta()
        result = serialize_meta(meta)

        assert set(result.keys()) == {
            "game_id",
            "game_version",
            "recorded_by",
            "started_at",
            "duration_seconds",
            "schema_version",
        }

    def test_schema_version_is_string_one(self) -> None:
        """schema_version in the serialized dict is the string "1", not int 1.

        Spec: Requirement "Session Metadata", Scenario "schema_version is literal '1'".
        """
        from gameplay_recorder.packaging.metadata import serialize_meta

        meta = _make_meta(schema_version="1")
        result = serialize_meta(meta)

        assert result["schema_version"] == "1"
        assert isinstance(result["schema_version"], str)

    def test_started_at_format(self) -> None:
        """started_at in the serialized dict matches YYYY-MM-DDTHH:MM:SSZ.

        Spec: Requirement "Session Metadata", Scenario "started_at is UTC ISO 8601".
        """
        from gameplay_recorder.packaging.metadata import serialize_meta

        meta = _make_meta(started_at="2026-04-28T14:00:00Z")
        result = serialize_meta(meta)

        pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
        assert re.match(pattern, result["started_at"]) is not None

    def test_field_values_match_input(self) -> None:
        """All 6 field values round-trip correctly through serialize_meta."""
        from gameplay_recorder.packaging.metadata import serialize_meta

        meta = _make_meta()
        result = serialize_meta(meta)

        assert result["game_id"] == "my_game"
        assert result["game_version"] == "1.32.1"
        assert result["recorded_by"] == "alice"
        assert result["started_at"] == "2026-04-28T14:00:00Z"
        assert result["duration_seconds"] == 42
        assert result["schema_version"] == "1"

    def test_duration_seconds_is_int(self) -> None:
        """duration_seconds must serialize as int, not string."""
        from gameplay_recorder.packaging.metadata import serialize_meta

        meta = _make_meta(duration_seconds=120)
        result = serialize_meta(meta)

        assert isinstance(result["duration_seconds"], int)
        assert result["duration_seconds"] == 120


class TestWriteMeta:
    """Tests for write_meta() — writes session_meta.json to a directory."""

    def test_write_meta_creates_json_file(self, tmp_path: Path) -> None:
        """write_meta writes session_meta.json into dest_dir.

        Spec: Requirement "Session Metadata", Scenario "Metadata file contents".
        """
        from gameplay_recorder.packaging.metadata import write_meta

        meta = _make_meta()
        write_meta(meta, tmp_path)

        json_file = tmp_path / "session_meta.json"
        assert json_file.exists()

    def test_write_meta_content_is_valid_json(self, tmp_path: Path) -> None:
        """write_meta writes valid JSON that can be parsed back."""
        from gameplay_recorder.packaging.metadata import write_meta

        meta = _make_meta()
        write_meta(meta, tmp_path)

        json_file = tmp_path / "session_meta.json"
        content = json.loads(json_file.read_text(encoding="utf-8"))
        assert isinstance(content, dict)

    def test_write_meta_json_has_exactly_6_keys(self, tmp_path: Path) -> None:
        """The JSON file produced by write_meta has exactly 6 top-level keys."""
        from gameplay_recorder.packaging.metadata import write_meta

        meta = _make_meta()
        write_meta(meta, tmp_path)

        json_file = tmp_path / "session_meta.json"
        content = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(content) == 6

    def test_write_meta_json_schema_version_is_string(self, tmp_path: Path) -> None:
        """After write_meta, JSON-parsed schema_version is a string "1", not int."""
        from gameplay_recorder.packaging.metadata import write_meta

        meta = _make_meta()
        write_meta(meta, tmp_path)

        json_file = tmp_path / "session_meta.json"
        content = json.loads(json_file.read_text(encoding="utf-8"))
        assert content["schema_version"] == "1"
        assert isinstance(content["schema_version"], str)

    def test_write_meta_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Calling write_meta twice overwrites the previous session_meta.json."""
        from gameplay_recorder.packaging.metadata import write_meta

        meta1 = _make_meta(game_id="game_a")
        meta2 = _make_meta(game_id="game_b")

        write_meta(meta1, tmp_path)
        write_meta(meta2, tmp_path)

        json_file = tmp_path / "session_meta.json"
        content = json.loads(json_file.read_text(encoding="utf-8"))
        assert content["game_id"] == "game_b"
