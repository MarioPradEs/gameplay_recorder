"""Data validation for gameplay_recorder packaging.

Phase 9: Schema validation for events.jsonl, game_id, and screenshot filenames.
Spec: Requirement "Raw Touch Event Capture", Scenario "Schema validation".

Validates that:
  - events.jsonl lines contain EXACTLY the 5 whitelisted fields with correct types.
  - game_id matches the regex ^[a-z][a-z0-9_]{1,31}$ (2-32 chars total).
  - Screenshot filenames match ^\\d{4}\\.png$.

Note: This validation ensures schema correctness for the consumer trainer.
It is NOT an IP-leak guard (the ZIPs are private); rather it prevents corrupt
or off-spec data from reaching the training pipeline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_EVENT_FIELDS: frozenset[str] = frozenset({"ts", "type", "x", "y", "slot"})
_ALLOWED_EVENT_TYPES: frozenset[str] = frozenset({"touch_down", "touch_up", "touch_move"})

_GAME_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_SCREENSHOT_RE = re.compile(r"^\d{4}\.png$")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DataValidationError(Exception):
    """Raised when events.jsonl (or other session data) fails schema validation.

    Signals that the packaging step cannot proceed because the data does not
    conform to the expected schema for the consumer training pipeline.
    """


# ---------------------------------------------------------------------------
# events.jsonl line validation
# ---------------------------------------------------------------------------


def validate_events_line(line: str) -> tuple[bool, str | None]:
    """Validate a single events.jsonl line against the 5-field whitelist.

    Rules (spec: Requirement "Raw Touch Event Capture"):
      - Must be valid JSON.
      - Must be a JSON object (dict), not an array or scalar.
      - Must have EXACTLY the 5 fields: ts, type, x, y, slot.
      - ts: float or int (numeric).
      - type: str in {"touch_down", "touch_up", "touch_move"}.
      - x, y, slot: int (not float, not str).
      - No extra fields allowed.

    Args:
        line: A single text line from events.jsonl.

    Returns:
        (True, None) if valid.
        (False, reason_string) if invalid.
    """
    stripped = line.strip()
    if not stripped:
        return False, "empty line"

    # Parse JSON
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}"

    # Must be a dict
    if not isinstance(obj, dict):
        return False, f"expected JSON object, got {type(obj).__name__}"

    keys = frozenset(obj.keys())

    # Check for extra fields
    extra = keys - _ALLOWED_EVENT_FIELDS
    if extra:
        return False, f"extra fields not allowed: {sorted(extra)}"

    # Check for missing fields
    missing = _ALLOWED_EVENT_FIELDS - keys
    if missing:
        return False, f"missing required fields: {sorted(missing)}"

    # Type checks
    ts = obj["ts"]
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return False, f"'ts' must be numeric, got {type(ts).__name__}"

    event_type = obj["type"]
    if not isinstance(event_type, str):
        return False, f"'type' must be str, got {type(event_type).__name__}"
    if event_type not in _ALLOWED_EVENT_TYPES:
        return False, f"'type' must be one of {sorted(_ALLOWED_EVENT_TYPES)}, got {event_type!r}"

    for field in ("x", "y", "slot"):
        val = obj[field]
        # Must be int, not float, not bool
        if not isinstance(val, int) or isinstance(val, bool):
            return False, f"'{field}' must be int, got {type(val).__name__} ({val!r})"

    return True, None


# ---------------------------------------------------------------------------
# events.jsonl file validation
# ---------------------------------------------------------------------------


def validate_events_file(
    path: Path,
) -> tuple[bool, list[dict[str, object]]]:
    """Validate all lines in an events.jsonl file.

    Reads each non-empty line, calls validate_events_line, and collects
    violations.

    Args:
        path: Path to the events.jsonl file.

    Returns:
        (True, []) if all lines are valid.
        (False, [{"line_number": int, "line": str, "reason": str}, ...])
        if any lines are invalid.
    """
    path = Path(path)
    rejected: list[dict[str, object]] = []

    text = path.read_text(encoding="utf-8")
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            # Blank lines are skipped silently
            continue
        ok, reason = validate_events_line(stripped)
        if not ok:
            rejected.append({"line_number": lineno, "line": raw_line, "reason": reason})

    return (len(rejected) == 0), rejected


# ---------------------------------------------------------------------------
# game_id validation
# ---------------------------------------------------------------------------


def validate_game_id(game_id: str) -> tuple[bool, str | None]:
    """Validate a game_id string against the spec regex.

    Spec: ^[a-z][a-z0-9_]{1,31}$ — 2-32 chars total, lowercase alphanumeric
    + underscore, must start with a letter.

    Args:
        game_id: The game identifier to validate.

    Returns:
        (True, None) if valid.
        (False, reason_string) if invalid.
    """
    if not game_id:
        return False, "game_id must not be empty"
    if not _GAME_ID_RE.match(game_id):
        return (
            False,
            f"game_id {game_id!r} does not match ^[a-z][a-z0-9_]{{1,31}}$ "
            f"(2-32 chars, lowercase alphanumeric + underscore, must start with a letter)",
        )
    return True, None


# ---------------------------------------------------------------------------
# Screenshot filename validation
# ---------------------------------------------------------------------------


def validate_screenshot_filename(filename: str) -> bool:
    r"""Validate a screenshot filename against the spec pattern.

    Spec: ^\d{4}\.png$ — exactly 4 digits followed by .png.

    Args:
        filename: The bare filename (not a full path), e.g. "0000.png".

    Returns:
        True if valid, False otherwise.
    """
    return bool(_SCREENSHOT_RE.match(filename))
