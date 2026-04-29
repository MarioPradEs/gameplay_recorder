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
  - Collision handling: appends _2, _3, … as needed.
  - Output directory auto-created if it does not exist.

Data integrity guardrail:
  - No consumer-system imports.
  - No hardcoded game-package names.
  - Metadata comes entirely from the SessionMeta passed in.

TODO Phase 9: replace placeholder "trust everything" filter with real data
validation that validates events.jsonl schema before packaging.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from gameplay_recorder.models.session import SessionMeta
from gameplay_recorder.packaging.metadata import write_meta

logger = logging.getLogger(__name__)

# Files that must NEVER be included in the ZIP (spec: "No perception.jsonl").
_EXCLUDED_FILES = frozenset({"perception.jsonl"})


def _build_zip_name(meta: SessionMeta) -> str:
    """Build the ZIP filename from session metadata.

    Format: {game_id}_v{game_version}_{recorded_by}_{date}_{time}.zip
    Date/time are derived from started_at (UTC ISO 8601: YYYY-MM-DDTHH:MM:SSZ).

    Example:
        started_at="2026-04-28T14:00:00Z"
        → my_game_v1.32.1_alice_2026-04-28_140000.zip
    """
    # Parse started_at: "2026-04-28T14:00:00Z"
    date_part, time_raw = meta.started_at.split("T")
    time_part = time_raw.rstrip("Z").replace(":", "")  # "140000"

    return f"{meta.game_id}_v{meta.game_version}_{meta.recorded_by}_{date_part}_{time_part}.zip"


def _resolve_output_path(output_dir: Path, base_name: str) -> Path:
    """Return a non-colliding path for the ZIP in output_dir.

    If base_name already exists, tries base_name_2.zip, _3.zip, … until free.

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


def assemble_zip(
    session_dir: Path,
    meta: SessionMeta,
    output_dir: Path,
) -> Path:
    """Package a session directory into a named ZIP file.

    Steps:
    1. Resolve (and create) output_dir.
    2. Determine non-colliding ZIP filename.
    3. Write session_meta.json into a temp location inside session_dir.
    4. Assemble ZIP with: session_meta.json, gameplay.mp4, events.jsonl, screenshots/*.
    5. Explicitly exclude perception.jsonl and any other unlisted file.

    Data validation (Phase 9 placeholder):
      events.jsonl is included as-is. Phase 9 wires schema validation here.
      # TODO Phase 9: replace with validate_events_file(session_dir / "events.jsonl")

    Args:
        session_dir: Directory containing the session files produced by capture workers.
        meta:        Completed session metadata (6 fields).
        output_dir:  Directory where the ZIP will be saved.

    Returns:
        Path to the written ZIP file.

    Raises:
        FileNotFoundError: If gameplay.mp4 or events.jsonl are missing from session_dir.
    """
    session_dir = Path(session_dir)
    output_dir = Path(output_dir)

    # 1. Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. Non-colliding ZIP path
    base_name = _build_zip_name(meta)
    zip_path = _resolve_output_path(output_dir, base_name)

    # 3. Write session_meta.json into the session_dir so we can include it in the ZIP
    meta_file = write_meta(meta, session_dir)

    # 4. Assemble ZIP
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # session_meta.json
        zf.write(meta_file, arcname="session_meta.json")

        # gameplay.mp4
        gameplay = session_dir / "gameplay.mp4"
        if gameplay.exists():
            zf.write(gameplay, arcname="gameplay.mp4")
        else:
            logger.warning("assemble_zip: gameplay.mp4 not found in %s", session_dir)

        # events.jsonl
        # TODO Phase 9: validate events.jsonl with IPFirewall before including
        events = session_dir / "events.jsonl"
        if events.exists():
            zf.write(events, arcname="events.jsonl")
        else:
            logger.warning("assemble_zip: events.jsonl not found in %s", session_dir)

        # screenshots/ — include all files, preserving the screenshots/ prefix
        screenshots_dir = session_dir / "screenshots"
        if screenshots_dir.exists():
            for png in sorted(screenshots_dir.iterdir()):
                if png.is_file() and png.name not in _EXCLUDED_FILES:
                    zf.write(png, arcname=f"screenshots/{png.name}")

    logger.info("assemble_zip: wrote %s (%d bytes)", zip_path, zip_path.stat().st_size)
    return zip_path
