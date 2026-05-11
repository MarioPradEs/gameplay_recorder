"""RED tests for touch_capture field in session_meta (Phase 4.1).

When recording started with escape-hatch active, session_meta.json must include
  "touch_capture": "disabled_by_user"
When recording was normal (touch device detected):
  "touch_capture": "enabled"

Spec: Phase 4 — session_meta enrichment for escape-hatch.
gameplay-recorder-shutdown-and-touch-fixes change.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from gameplay_recorder.models.session import SessionMeta


def _make_meta(**overrides) -> SessionMeta:
    """Build a valid SessionMeta."""
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
    """Create a minimal session directory."""
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "gameplay.mp4").write_bytes(b"fake-video")
    (session_dir / "events.jsonl").write_text(
        '{"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0}\n',
        encoding="utf-8",
    )
    screenshots = session_dir / "screenshots"
    screenshots.mkdir()
    (screenshots / "0000.png").write_bytes(b"fake-png")
    return session_dir


class TestTouchCaptureField:
    """assemble_zip includes touch_capture field in session_meta.json."""

    def test_session_meta_includes_disabled_by_user_when_escape_hatch(self, tmp_path: Path) -> None:
        """When escape_hatch_active=True, session_meta has touch_capture='disabled_by_user'.

        Spec: Phase 4 — escape-hatch enrichment of session_meta.json.
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir, escape_hatch_active=True)

        with zipfile.ZipFile(result) as zf:
            content = json.loads(zf.read("session_meta.json").decode("utf-8"))

        assert content["touch_capture"] == "disabled_by_user", (
            f"Expected 'disabled_by_user', got: {content.get('touch_capture')!r}"
        )

    def test_session_meta_includes_enabled_when_normal_recording(self, tmp_path: Path) -> None:
        """When escape_hatch_active=False (default), session_meta has touch_capture='enabled'.

        Spec: Phase 4 — normal recording enrichment.
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        result = assemble_zip(session_dir, meta, output_dir, escape_hatch_active=False)

        with zipfile.ZipFile(result) as zf:
            content = json.loads(zf.read("session_meta.json").decode("utf-8"))

        assert content["touch_capture"] == "enabled", (
            f"Expected 'enabled', got: {content.get('touch_capture')!r}"
        )

    def test_session_meta_default_escape_hatch_is_enabled(self, tmp_path: Path) -> None:
        """When escape_hatch_active not specified (default), touch_capture='enabled'.

        Triangulation: the parameter defaults to False (normal flow).
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        session_dir = _make_session_dir(tmp_path)
        meta = _make_meta()
        output_dir = tmp_path / "out"

        # Call without escape_hatch_active — should default to False → "enabled"
        result = assemble_zip(session_dir, meta, output_dir)

        with zipfile.ZipFile(result) as zf:
            content = json.loads(zf.read("session_meta.json").decode("utf-8"))

        assert content["touch_capture"] == "enabled"

    def test_touch_capture_field_present_in_both_cases(self, tmp_path: Path) -> None:
        """touch_capture field is present in session_meta.json in both cases.

        Triangulation: the field is ALWAYS written, never omitted.
        """
        from gameplay_recorder.packaging.zipper import assemble_zip

        for i, (escape_hatch_active, expected) in enumerate(
            [
                (True, "disabled_by_user"),
                (False, "enabled"),
            ]
        ):
            session_dir = _make_session_dir(tmp_path / f"sess_{i}")
            meta = _make_meta()
            out = tmp_path / f"out_{i}"

            result = assemble_zip(session_dir, meta, out, escape_hatch_active=escape_hatch_active)

            with zipfile.ZipFile(result) as zf:
                content = json.loads(zf.read("session_meta.json").decode("utf-8"))

            assert "touch_capture" in content, (
                f"touch_capture missing from session_meta when escape_hatch_active={escape_hatch_active}"
            )
            assert content["touch_capture"] == expected
