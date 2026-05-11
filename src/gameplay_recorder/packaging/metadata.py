"""Session metadata serialization and persistence.

Produces `session_meta.json` with EXACTLY 6 fields — no more, no less.
Spec: Requirement "Session Metadata".
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from gameplay_recorder.models.session import SessionMeta

_FILENAME = "session_meta.json"


def serialize_meta(meta: SessionMeta) -> dict[str, object]:
    """Serialize a SessionMeta to a plain dict with exactly 6 keys.

    The dict contains ONLY the 6 spec-required fields:
      game_id, game_version, recorded_by, started_at,
      duration_seconds, schema_version.

    No extra fields are added. schema_version is always a string.

    Args:
        meta: The session metadata to serialize.

    Returns:
        A dict with exactly 6 keys matching the spec.
    """
    raw = dataclasses.asdict(meta)
    # Enforce the 6-field contract explicitly — extra fields (future additions)
    # must NOT leak into the output.
    allowed = {
        "game_id",
        "game_version",
        "recorded_by",
        "started_at",
        "duration_seconds",
        "schema_version",
    }
    result = {k: v for k, v in raw.items() if k in allowed}
    # schema_version MUST be a string "1", never int.
    result["schema_version"] = str(result["schema_version"])
    return result


def write_meta(
    meta: SessionMeta,
    dest_dir: Path,
    *,
    extra: dict[str, object] | None = None,
) -> Path:
    """Write session_meta.json into dest_dir.

    Creates dest_dir if it does not exist.
    Overwrites any existing session_meta.json.

    Args:
        meta:     The session metadata to persist.
        dest_dir: Directory where session_meta.json will be written.
        extra:    Optional additional fields to merge into the JSON output.
                  These are appended AFTER the 6 canonical fields.

    Returns:
        Path to the written file.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    json_path = dest_dir / _FILENAME
    payload = serialize_meta(meta)
    if extra:
        payload.update(extra)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return json_path
