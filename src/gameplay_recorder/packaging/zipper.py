"""ZIP assembler for completed recording sessions.

Packages a session directory into a named ZIP:
  {game_id}_v{game_version}_{recorded_by}_{YYYY-MM-DD}_{HHMMSS}.zip

ZIP contents (spec: Requirement "ZIP Packaging"):
  - session_meta.json     (6-field metadata, generated fresh from SessionMeta)
  - gameplay.mp4          (from session_dir)
  - events.jsonl          (from session_dir)
  - screenshots/          (all *.png files from session_dir/screenshots/)

Explicitly EXCLUDED (spec: "No perception.jsonl"):
  - perception.jsonl

Naming conventions:
  - Collision handling: appends _2, _3, ... as needed.
  - Output directory auto-created if it does not exist.

IP-leak guardrail:
  - No bot_neuronal imports.
  - No hardcoded game-package names.
  - Metadata comes entirely from the SessionMeta passed in.

Phase 9: Schema validation is applied before packaging:
  - game_id is validated against the spec regex.
  - events.jsonl is validated line-by-line (5-field whitelist).
  - Screenshot filenames are validated against 4-digit pattern.
  - DataValidationError is raised on any violation; events.rejected.jsonl
    is written to output_dir for local debugging.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from gameplay_recorder.models.session import SessionMeta
from gameplay_recorder.packaging.metadata import write_meta
from gameplay_recorder.packaging.validation import (
    DataValidationError,
    validate_events_file,
    validate_game_id,
    validate_screenshot_filename,
)

logger = logging.getLogger(__name__)

# Files that must NEVER be included in the ZIP (spec: "No perception.jsonl").
_EXCLUDED_FILES = frozenset({"perception.jsonl"})


def _build_zip_name(meta: SessionMeta) -> str:
    """Build the ZIP filename from session metadata.

    Format: {game_id}_v{game_version}_{recorded_by}_{date}_{time}.zip
    Date/time are derived from started_at (UTC ISO 8601: YYYY-MM-DDTHH:MM:SSZ).

    Example:
        started_at="2026-04-28T14:00:00Z"
        -> zombie_gore_v1.32.1_alice_2026-04-28_140000.zip
    """
    # Parse started_at: "2026-04-28T14:00:00Z"
    date_part, time_raw = meta.started_at.split("T")
    time_part = time_raw.rstrip("Z").replace(":", "")  # "140000"

    return f"{meta.game_id}_v{meta.game_version}_{meta.recorded_by}_{date_part}_{time_part}.zip"


def _resolve_output_path(output_dir: Path, base_name: str) -> Path:
    """Return a non-colliding path for the ZIP in output_dir.

    If base_name already exists, tries base_name_2.zip, _3.zip, ... until free.

    Args:
        output_dir: Directory where the ZIP will be saved.
        base_name:  Desired filename including .zip suffix.

    Returns:
        Path that does not currently exist in output_dir.
    """
    stem = base_name[: -len(".zip")]  # strip .zip
    candidate = output_dir / base_name
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = output_dir / f"{stem}_{counter}.zip"
        if not candidate.exists():
            return candidate
        counter += 1


def _write_rejected_jsonl(output_dir: Path, violations: list[dict[str, object]]) -> Path:
    """Write events.rejected.jsonl to output_dir for local debugging.

    The file is a single JSON object (not JSONL) summarising all violations.
    It is NOT included in any ZIP — it stays as a sibling file in output_dir.

    Args:
        output_dir:  Directory where the rejected file will be saved.
        violations:  List of violation dicts from validate_events_file.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    rejected_path = output_dir / "events.rejected.jsonl"
    payload = {
        "violation_count": len(violations),
        "violations": violations,
    }
    rejected_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.warning(
        "assemble_zip: validation failed — %d violations written to %s",
        len(violations),
        rejected_path,
    )
    return rejected_path


def assemble_zip(
    session_dir: Path,
    meta: SessionMeta,
    output_dir: Path,
    *,
    escape_hatch_active: bool = False,
) -> Path:
    """Package a session directory into a named ZIP file.

    Phase 9 validation (runs BEFORE any ZIP is written):
      1. Validate game_id against spec regex.
      2. Validate events.jsonl line-by-line (5-field whitelist).
      3. Validate screenshot filenames (4-digit .png pattern).
      On any failure: write events.rejected.jsonl to output_dir; raise DataValidationError.

    Assembly steps (only reached if validation passes):
      1. Resolve (and create) output_dir.
      2. Determine non-colliding ZIP filename.
      3. Write session_meta.json into session_dir.
      4. Assemble ZIP: session_meta.json, gameplay.mp4, events.jsonl, screenshots/*.
      5. Exclude perception.jsonl and any unlisted file.

    Phase 4: escape_hatch_active controls the touch_capture field in session_meta.json:
      - True  → touch_capture: "disabled_by_user"
      - False → touch_capture: "enabled"

    Args:
        session_dir:         Directory containing session files produced by capture workers.
        meta:                Completed session metadata (6 fields).
        output_dir:          Directory where the ZIP will be saved.
        escape_hatch_active: Whether the user started recording with no touch device
                             (escape-hatch checkbox was checked).

    Returns:
        Path to the written ZIP file.

    Raises:
        DataValidationError: If game_id, events.jsonl, or screenshot filenames fail validation.
        FileNotFoundError: If gameplay.mp4 or events.jsonl are missing from session_dir.
    """
    session_dir = Path(session_dir)
    output_dir = Path(output_dir)

    # ── Phase 9: Pre-packaging validation ─────────────────────────────────────

    # 1. Validate game_id
    ok, reason = validate_game_id(meta.game_id)
    if not ok:
        raise DataValidationError(f"Invalid game_id {meta.game_id!r}: {reason}")

    # 2. Validate events.jsonl
    events_path = session_dir / "events.jsonl"
    if events_path.exists():
        valid, violations = validate_events_file(events_path)
        if not valid:
            _write_rejected_jsonl(output_dir, violations)
            raise DataValidationError(
                f"events.jsonl has {len(violations)} validation violation(s). "
                f"See {output_dir / 'events.rejected.jsonl'} for details."
            )

    # 3. Validate screenshot filenames
    screenshots_dir = session_dir / "screenshots"
    if screenshots_dir.exists():
        bad_screenshots = [
            png.name
            for png in screenshots_dir.iterdir()
            if png.is_file() and not validate_screenshot_filename(png.name)
        ]
        if bad_screenshots:
            raise DataValidationError(
                f"Invalid screenshot filename(s) (expected 4-digit .png): {bad_screenshots}"
            )

    # ── Required file presence check (before any ZIP is written) ──────────────

    gameplay = session_dir / "gameplay.mp4"
    if not gameplay.exists():
        raise FileNotFoundError(
            f"assemble_zip: gameplay.mp4 not found in {session_dir}. "
            "Recording may have failed — no video segments were produced."
        )

    events_path_check = session_dir / "events.jsonl"
    if not events_path_check.exists():
        raise FileNotFoundError(
            f"assemble_zip: events.jsonl not found in {session_dir}. "
            "TouchEventMonitor may not have been started."
        )

    # ── Assembly ───────────────────────────────────────────────────────────────

    # 1. Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. Non-colliding ZIP path
    base_name = _build_zip_name(meta)
    zip_path = _resolve_output_path(output_dir, base_name)

    # 3. Write session_meta.json into the session_dir so we can include it in the ZIP
    # Phase 4: include touch_capture field to record whether escape-hatch was used.
    touch_capture_value = "disabled_by_user" if escape_hatch_active else "enabled"
    meta_file = write_meta(meta, session_dir, extra={"touch_capture": touch_capture_value})

    # 4. Assemble ZIP
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # session_meta.json
        zf.write(meta_file, arcname="session_meta.json")

        # gameplay.mp4 — presence guaranteed by required-file check above
        zf.write(gameplay, arcname="gameplay.mp4")

        # events.jsonl — presence guaranteed by required-file check above
        zf.write(events_path, arcname="events.jsonl")

        # screenshots/ — include all files, preserving the screenshots/ prefix
        if screenshots_dir.exists():
            for png in sorted(screenshots_dir.iterdir()):
                if png.is_file() and png.name not in _EXCLUDED_FILES:
                    zf.write(png, arcname=f"screenshots/{png.name}")

    logger.info("assemble_zip: wrote %s (%d bytes)", zip_path, zip_path.stat().st_size)
    return zip_path
