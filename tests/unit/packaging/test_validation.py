"""Tests for gameplay_recorder.packaging.validation.

Phase 9: Data Validation — Strict TDD (RED first).
Spec: Requirement "Raw Touch Event Capture", Scenario "Schema validation".

Validates events.jsonl line-by-line against the 5-field whitelist:
  ts (float), type (str ∈ allowed), x (int), y (int), slot (int).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gameplay_recorder.packaging.validation import (
    DataValidationError,
    validate_events_file,
    validate_events_line,
)

# ---------------------------------------------------------------------------
# validate_events_line — unit tests (pure function)
# ---------------------------------------------------------------------------


class TestValidateEventsLineAccepts:
    """Valid lines: all 5 required fields, correct types, correct type values."""

    def test_touch_down_valid(self) -> None:
        """touch_down with correct 5 fields is accepted."""
        line = json.dumps({"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is True
        assert reason is None

    def test_touch_up_valid(self) -> None:
        """touch_up is a valid type value."""
        line = json.dumps({"ts": 2.5, "type": "touch_up", "x": 50, "y": 75, "slot": 1})
        ok, reason = validate_events_line(line)
        assert ok is True

    def test_touch_move_valid(self) -> None:
        """touch_move is a valid type value."""
        line = json.dumps({"ts": 0.001, "type": "touch_move", "x": 0, "y": 0, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is True

    def test_ts_as_integer_is_valid(self) -> None:
        """ts stored as an int literal in JSON (e.g. 1) still satisfies float requirement."""
        # JSON doesn't distinguish int from float when both are valid numbers
        line = json.dumps({"ts": 1, "type": "touch_down", "x": 10, "y": 20, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is True


class TestValidateEventsLineRejectsExtraFields:
    """Any extra field beyond the 5 whitelisted ones must be rejected."""

    def test_rejects_reward_signals_field(self) -> None:
        line = json.dumps(
            {"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0, "reward": 1.0}
        )
        ok, reason = validate_events_line(line)
        assert ok is False
        assert reason is not None

    def test_rejects_obs_vector_field(self) -> None:
        line = json.dumps(
            {
                "ts": 1.0,
                "type": "touch_down",
                "x": 100,
                "y": 200,
                "slot": 0,
                "obs_vector": [1, 2, 3],
            }
        )
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_action_id_field(self) -> None:
        line = json.dumps(
            {"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0, "action_id": 42}
        )
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_episode_id_field(self) -> None:
        line = json.dumps(
            {"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0, "episode_id": "ep1"}
        )
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_arbitrary_extra_field(self) -> None:
        """Any unknown field triggers rejection."""
        line = json.dumps(
            {"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": 0, "strategy_hint": "A"}
        )
        ok, reason = validate_events_line(line)
        assert ok is False


class TestValidateEventsLineRejectsMissingFields:
    """Missing required fields must be rejected."""

    def test_rejects_missing_ts(self) -> None:
        line = json.dumps({"type": "touch_down", "x": 100, "y": 200, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_missing_type(self) -> None:
        line = json.dumps({"ts": 1.0, "x": 100, "y": 200, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_missing_x(self) -> None:
        line = json.dumps({"ts": 1.0, "type": "touch_down", "y": 200, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_missing_slot(self) -> None:
        line = json.dumps({"ts": 1.0, "type": "touch_down", "x": 100, "y": 200})
        ok, reason = validate_events_line(line)
        assert ok is False


class TestValidateEventsLineRejectsWrongTypes:
    """Fields with wrong Python types must be rejected."""

    def test_rejects_ts_as_string(self) -> None:
        line = json.dumps({"ts": "1.0", "type": "touch_down", "x": 100, "y": 200, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_x_as_float(self) -> None:
        """x must be int, not float (e.g. 100.5 is invalid)."""
        line = json.dumps({"ts": 1.0, "type": "touch_down", "x": 100.5, "y": 200, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_slot_as_string(self) -> None:
        line = json.dumps({"ts": 1.0, "type": "touch_down", "x": 100, "y": 200, "slot": "0"})
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_invalid_type_value(self) -> None:
        """type must be one of the three allowed strings."""
        line = json.dumps({"ts": 1.0, "type": "tap", "x": 100, "y": 200, "slot": 0})
        ok, reason = validate_events_line(line)
        assert ok is False

    def test_rejects_malformed_json(self) -> None:
        """Non-JSON line is rejected."""
        ok, reason = validate_events_line("not json at all")
        assert ok is False
        assert reason is not None

    def test_rejects_empty_line(self) -> None:
        """Empty string is rejected."""
        ok, reason = validate_events_line("")
        assert ok is False

    def test_rejects_json_array_not_object(self) -> None:
        """JSON arrays are not valid event lines."""
        ok, reason = validate_events_line("[1, 2, 3]")
        assert ok is False


# ---------------------------------------------------------------------------
# validate_events_file — integration-style tests using tmp_path
# ---------------------------------------------------------------------------


class TestValidateEventsFile:
    """Tests for validate_events_file(path) → (valid: bool, rejected: list[dict])."""

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        """5 valid lines → (True, [])."""
        events = tmp_path / "events.jsonl"
        events.write_text(
            "\n".join(
                json.dumps({"ts": float(i), "type": "touch_down", "x": i, "y": i, "slot": 0})
                for i in range(5)
            )
            + "\n",
            encoding="utf-8",
        )
        valid, rejected = validate_events_file(events)
        assert valid is True
        assert rejected == []

    def test_mixed_file_returns_violations(self, tmp_path: Path) -> None:
        """File with 2 good lines + 1 bad line returns (False, [violation_info])."""
        events = tmp_path / "events.jsonl"
        lines = [
            json.dumps({"ts": 1.0, "type": "touch_down", "x": 0, "y": 0, "slot": 0}),
            json.dumps(
                {
                    "ts": 2.0,
                    "type": "touch_up",
                    "x": 0,
                    "y": 0,
                    "slot": 0,
                    "action_id": "bad",
                }
            ),
            json.dumps({"ts": 3.0, "type": "touch_move", "x": 1, "y": 1, "slot": 0}),
        ]
        events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        valid, rejected = validate_events_file(events)
        assert valid is False
        assert len(rejected) == 1
        assert rejected[0]["line_number"] == 2

    def test_all_bad_lines_returns_all_violations(self, tmp_path: Path) -> None:
        """Every bad line is reported."""
        events = tmp_path / "events.jsonl"
        lines = [
            json.dumps({"ts": 1.0, "type": "touch_down", "x": 0, "y": 0, "slot": 0, "x_bad": 1}),
            json.dumps({"ts": 2.0, "type": "touch_up", "x": 0, "y": 0, "slot": 0, "y_bad": 2}),
        ]
        events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        valid, rejected = validate_events_file(events)
        assert valid is False
        assert len(rejected) == 2

    def test_empty_file_passes(self, tmp_path: Path) -> None:
        """An empty events.jsonl has no violations — it's trivially clean."""
        events = tmp_path / "events.jsonl"
        events.write_text("", encoding="utf-8")
        valid, rejected = validate_events_file(events)
        assert valid is True
        assert rejected == []

    def test_file_with_blank_lines_skips_them(self, tmp_path: Path) -> None:
        """Blank lines inside the file are ignored (not flagged as violations)."""
        events = tmp_path / "events.jsonl"
        events.write_text(
            json.dumps({"ts": 1.0, "type": "touch_down", "x": 0, "y": 0, "slot": 0})
            + "\n\n"
            + json.dumps({"ts": 2.0, "type": "touch_up", "x": 1, "y": 1, "slot": 0})
            + "\n",
            encoding="utf-8",
        )
        valid, rejected = validate_events_file(events)
        assert valid is True
        assert rejected == []


# ---------------------------------------------------------------------------
# game_id validation — validate_game_id()
# ---------------------------------------------------------------------------


class TestValidateGameId:
    """Spec: game_id must match ^[a-z][a-z0-9_]{1,31}$ (2-32 chars total)."""

    def test_valid_game_id(self) -> None:
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("my_game")
        assert ok is True
        assert reason is None

    def test_valid_game_id_with_numbers(self) -> None:
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, _ = validate_game_id("game_v2")
        assert ok is True

    def test_rejects_uppercase(self) -> None:
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("MyGame")
        assert ok is False
        assert reason is not None

    def test_rejects_starting_with_digit(self) -> None:
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("1game")
        assert ok is False

    def test_rejects_too_short(self) -> None:
        """Only 1 char is too short (min 2 chars)."""
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("a")
        assert ok is False

    def test_rejects_too_long(self) -> None:
        """33 chars is too long (max 32)."""
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("a" * 33)
        assert ok is False

    def test_valid_32_chars(self) -> None:
        """Exactly 32 chars is valid."""
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, _ = validate_game_id("a" + "b" * 31)
        assert ok is True

    def test_rejects_hyphen(self) -> None:
        """Hyphens are not allowed — only alphanumeric and underscore."""
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("my-game")
        assert ok is False

    def test_rejects_space(self) -> None:
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("my game")
        assert ok is False

    def test_rejects_empty(self) -> None:
        from gameplay_recorder.packaging.validation import validate_game_id

        ok, reason = validate_game_id("")
        assert ok is False


# ---------------------------------------------------------------------------
# screenshot filename validation — validate_screenshot_filename()
# ---------------------------------------------------------------------------


class TestValidateScreenshotFilename:
    r"""Spec: screenshot filenames must match ^\d{4}\.png$."""

    def test_valid_0000(self) -> None:
        from gameplay_recorder.packaging.validation import validate_screenshot_filename

        assert validate_screenshot_filename("0000.png") is True

    def test_valid_9999(self) -> None:
        from gameplay_recorder.packaging.validation import validate_screenshot_filename

        assert validate_screenshot_filename("9999.png") is True

    def test_rejects_no_leading_zeros(self) -> None:
        from gameplay_recorder.packaging.validation import validate_screenshot_filename

        assert validate_screenshot_filename("1.png") is False

    def test_rejects_five_digits(self) -> None:
        from gameplay_recorder.packaging.validation import validate_screenshot_filename

        assert validate_screenshot_filename("00001.png") is False

    def test_rejects_wrong_extension(self) -> None:
        from gameplay_recorder.packaging.validation import validate_screenshot_filename

        assert validate_screenshot_filename("0000.jpg") is False

    def test_rejects_no_extension(self) -> None:
        from gameplay_recorder.packaging.validation import validate_screenshot_filename

        assert validate_screenshot_filename("0000") is False

    def test_rejects_letters(self) -> None:
        from gameplay_recorder.packaging.validation import validate_screenshot_filename

        assert validate_screenshot_filename("abcd.png") is False


# ---------------------------------------------------------------------------
# DataValidationError
# ---------------------------------------------------------------------------


class TestDataValidationError:
    def test_is_exception(self) -> None:
        """DataValidationError must be a subclass of Exception."""
        assert issubclass(DataValidationError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(DataValidationError):
            raise DataValidationError("test message")

    def test_carries_message(self) -> None:
        err = DataValidationError("events.jsonl has 3 violations")
        assert "events.jsonl" in str(err)
