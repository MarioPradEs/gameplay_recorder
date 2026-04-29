"""Tests for gameplay_recorder.packaging.zipper.

Phase 8: Packaging / ZIP Assembler — Strict TDD.
Spec: Requirement "ZIP Packaging".
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from gameplay_recorder.models.session import SessionMeta


def _make_meta(**overrides) -> SessionMeta:
    """Helper: build a valid SessionMeta."""
    defaults = dict(
        game_id="zombie_gore",
        game_version="1.32.1",
        recorded_by="alice",
        started_at="2026-04-28T14:00:00Z",
        duration_seconds=42,
        schema_version="1",
    )
    defaults.update(overrides)
    return SessionMeta(**defaults)


def _make_session_dir(tmp_path: Path) -> Path:
    """Create a minimal session directory with the files assemble_zip expects."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    # gameplay.mp4
    (session_dir / "gameplay.mp4").write_bytes(b"fake-video")

    # events.jsonl — only allowed fields
    (session_dir / "events.jsonl").write_text(
        '{"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0}\n',
        encoding="utf-8",
    )

    # screenshots/
    screenshots = session_dir / "screenshots"
    screenshots.mkdir()
    (screenshots / "0000.png").write_bytes(b"fake-png-0")
    (screenshots / "0001.png").write_bytes(b"fake-png-1")

    return session_dir


class TestZipFilenameFormat:
    """Tests for ZIP filename generation."""

    def test_zip_filename_format(self, tmp_path: Path) -> None:
        """ZIP filename is {game_id}_v{game_version}_{recorded_by}_{date}_{time}.zip.

        Spec: Requirement "ZIP Packaging", Scenario "Filename format".
        game_id="zombie_gore", game_version="1.32.1", recorded_by="alice",
        started_at="2026-04-28T14:00:00Z" → zombie_gore_v1.32.1_alice_2026-04-28_140000.zip
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta(
            game_id="zombie_gore",
            game_version="1.32.1",
            recorded_by="alice",
            started_at="2026-04-28T14:00:00Z",
        )
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        assert result.name == "zombie_gore_v1.32.1_alice_2026-04-28_140000.zip"

    def test_zip_filename_uses_started_at_for_date_time(self, tmp_path: Path) -> None:
        """The date and time components in the filename come from started_at."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta(started_at="2025-12-31T23:59:59Z")
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        assert "2025-12-31" in result.name
        assert "235959" in result.name


class TestZipContents:
    """Tests for required and forbidden ZIP contents."""

    def test_zip_contains_required_files(self, tmp_path: Path) -> None:
        """ZIP contains session_meta.json, gameplay.mp4, events.jsonl, screenshots/.

        Spec: Requirement "ZIP Packaging", Scenario "Valid ZIP produced".
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()

        assert "session_meta.json" in names
        assert "gameplay.mp4" in names
        assert "events.jsonl" in names
        # screenshots directory should be present as entries
        screenshot_entries = [n for n in names if n.startswith("screenshots/")]
        assert len(screenshot_entries) > 0

    def test_zip_excludes_perception_jsonl(self, tmp_path: Path) -> None:
        """perception.jsonl MUST NOT be included in the ZIP.

        Spec: Requirement "ZIP Packaging", Scenario "No perception.jsonl".
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        # Create a perception.jsonl in the session dir — must NOT end up in ZIP
        (session_dir / "perception.jsonl").write_text('{"obs_vector": [1,2,3]}\n', encoding="utf-8")
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()

        assert "perception.jsonl" not in names

    def test_zip_contains_all_screenshot_pngs(self, tmp_path: Path) -> None:
        """All screenshots/*.png files are included in the ZIP."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()

        assert "screenshots/0000.png" in names
        assert "screenshots/0001.png" in names

    def test_zip_session_meta_is_valid_json_with_6_keys(self, tmp_path: Path) -> None:
        """session_meta.json inside the ZIP has exactly 6 keys, correct values."""
        import json

        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        with zipfile.ZipFile(result) as zf:
            content = json.loads(zf.read("session_meta.json").decode("utf-8"))

        assert len(content) == 6
        assert content["game_id"] == "zombie_gore"
        assert content["schema_version"] == "1"
        assert isinstance(content["schema_version"], str)


class TestZipFilenameCollision:
    """Tests for filename collision handling."""

    def test_zip_filename_collision_appends_suffix(self, tmp_path: Path) -> None:
        """Existing ZIP: new one is saved as ..._2.zip.

        Spec: Requirement "ZIP Packaging", Scenario "Filename collision".
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        # Create the collision file
        base_name = "zombie_gore_v1.32.1_alice_2026-04-28_140000.zip"
        (output_dir / base_name).write_bytes(b"existing")

        result = assemble_zip(session_dir, meta, output_dir)

        assert result.name == "zombie_gore_v1.32.1_alice_2026-04-28_140000_2.zip"

    def test_zip_filename_collision_suffix_increments_further(self, tmp_path: Path) -> None:
        """Two existing ZIPs: next one appends _3."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        base = "zombie_gore_v1.32.1_alice_2026-04-28_140000.zip"
        base2 = "zombie_gore_v1.32.1_alice_2026-04-28_140000_2.zip"
        (output_dir / base).write_bytes(b"existing1")
        (output_dir / base2).write_bytes(b"existing2")

        result = assemble_zip(session_dir, meta, output_dir)

        assert result.name == "zombie_gore_v1.32.1_alice_2026-04-28_140000_3.zip"


class TestZipOutputDirectory:
    """Tests for output directory handling."""

    def test_output_dir_auto_created(self, tmp_path: Path) -> None:
        """Non-existent output directory is created before saving ZIP.

        Spec: Requirement "ZIP Packaging", Scenario "Output directory auto-created".
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "new_dir" / "sub_dir"  # Neither exists

        result = assemble_zip(session_dir, meta, output_dir)

        assert output_dir.exists()
        assert result.exists()
        assert result.parent == output_dir

    def test_zip_is_a_valid_zip_file(self, tmp_path: Path) -> None:
        """The output file is a valid ZIP archive (not corrupt)."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        assert zipfile.is_zipfile(result)

    def test_zip_with_zero_screenshots(self, tmp_path: Path) -> None:
        """ZIP assembler works when screenshots/ directory is empty."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        # Remove all screenshots
        for f in (session_dir / "screenshots").iterdir():
            f.unlink()
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        assert zipfile.is_zipfile(result)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
        assert "session_meta.json" in names
        assert "gameplay.mp4" in names

    def test_zip_with_many_screenshots(self, tmp_path: Path) -> None:
        """ZIP assembler handles a large number of screenshots (1000)."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        screenshots = session_dir / "screenshots"
        # Add 1000 extra screenshots beyond the 2 from _make_session_dir
        for i in range(2, 1002):
            (screenshots / f"{i:04d}.png").write_bytes(b"px")

        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        with zipfile.ZipFile(result) as zf:
            png_count = sum(1 for n in zf.namelist() if n.startswith("screenshots/"))

        # original 2 + 1000 new = 1002
        assert png_count == 1002


# ---------------------------------------------------------------------------
# Phase 9: Data validation integration tests
# ---------------------------------------------------------------------------


class TestZipValidation:
    """Phase 9 — assemble_zip raises DataValidationError on invalid events.jsonl.

    Spec: Requirement "ZIP Packaging", Scenario "Data validation".
    """

    def test_clean_events_passes_validation(self, tmp_path: Path) -> None:
        """Valid events.jsonl (5 fields only) → ZIP is created successfully."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)

        assert result.exists()
        assert zipfile.is_zipfile(result)

    def test_dirty_events_raises_data_validation_error(self, tmp_path: Path) -> None:
        """events.jsonl with an extra field raises DataValidationError before writing ZIP.

        Spec: "DataValidationError raised when events.jsonl has invalid lines".
        """
        from gameplay_recorder.packaging.validation import DataValidationError
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        # Overwrite events.jsonl with a dirty line (extra field)
        dirty = (
            '{"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0,'
            ' "strategy_hint": "A"}\n'
        )
        (session_dir / "events.jsonl").write_text(dirty, encoding="utf-8")
        meta = _make_meta()
        output_dir = tmp_path / "out"

        with pytest.raises(DataValidationError):
            assemble_zip(session_dir, meta, output_dir)

    def test_dirty_events_writes_rejected_jsonl_sibling(self, tmp_path: Path) -> None:
        """When validation fails, events.rejected.jsonl is written next to the (non-created) ZIP.

        Spec: "events.rejected.jsonl written in output_dir on validation failure".
        """
        import json as _json

        from gameplay_recorder.packaging.validation import DataValidationError
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        dirty = (
            '{"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0,'
            ' "strategy_hint": "A"}\n'
        )
        (session_dir / "events.jsonl").write_text(dirty, encoding="utf-8")
        meta = _make_meta()
        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)

        with pytest.raises(DataValidationError):
            assemble_zip(session_dir, meta, output_dir)

        rejected_file = output_dir / "events.rejected.jsonl"
        assert rejected_file.exists(), "events.rejected.jsonl must be written next to the ZIP"
        content = _json.loads(rejected_file.read_text(encoding="utf-8"))
        assert content["violation_count"] >= 1
        assert len(content["violations"]) >= 1

    def test_dirty_events_no_zip_written(self, tmp_path: Path) -> None:
        """When validation fails, no ZIP file is created in output_dir."""
        from gameplay_recorder.packaging.validation import DataValidationError
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        (session_dir / "events.jsonl").write_text(
            '{"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0, "bad_field": 1}\n',
            encoding="utf-8",
        )
        meta = _make_meta()
        output_dir = tmp_path / "out"

        with pytest.raises(DataValidationError):
            assemble_zip(session_dir, meta, output_dir)

        zips = list(output_dir.glob("*.zip")) if output_dir.exists() else []
        assert zips == [], f"No ZIP should exist on validation failure, found: {zips}"

    def test_invalid_game_id_raises_data_validation_error(self, tmp_path: Path) -> None:
        """game_id not matching regex raises DataValidationError."""
        from gameplay_recorder.packaging.validation import DataValidationError
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta(game_id="Bad Name!")
        output_dir = tmp_path / "out"

        with pytest.raises(DataValidationError):
            assemble_zip(session_dir, meta, output_dir)

    def test_invalid_screenshot_filename_raises_data_validation_error(self, tmp_path: Path) -> None:
        """Screenshot file not matching 4-digit pattern raises DataValidationError."""
        from gameplay_recorder.packaging.validation import DataValidationError
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        # Add a screenshot with invalid name
        (session_dir / "screenshots" / "bad_name.png").write_bytes(b"px")
        meta = _make_meta()
        output_dir = tmp_path / "out"

        with pytest.raises(DataValidationError):
            assemble_zip(session_dir, meta, output_dir)


class TestZipValidationGameId:
    """game_id validation at assemble_zip level."""

    def test_valid_game_id_passes(self, tmp_path: Path) -> None:
        """A game_id matching the regex succeeds."""
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta(game_id="mobile_game_v2")
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir)
        assert result.exists()
