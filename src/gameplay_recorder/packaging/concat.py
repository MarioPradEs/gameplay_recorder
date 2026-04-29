"""ffmpeg concat demuxer wrapper.

Assembles video segments into a single gameplay.mp4 using lossless concat
(copy codec — no re-encode). For single-segment sessions, skips ffmpeg entirely.

Resolves ffmpeg:
1. sys._MEIPASS/ffmpeg/ — bundled binary in PyInstaller one-folder build
2. shutil.which("ffmpeg") — system-installed ffmpeg fallback

Spec: Requirement "Segmented Video Capture", Scenarios:
  - "Short session < 170s": single segment → no ffmpeg call
  - "Multi-segment concat": N≥2 segments → ffmpeg -f concat -safe 0 -c copy
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_ffmpeg() -> str:
    """Return the path to the ffmpeg executable.

    Checks bundled binary first (PyInstaller _MEIPASS), then falls back
    to a system-installed ffmpeg on PATH.

    Raises:
        FileNotFoundError: If ffmpeg cannot be found.
    """
    # 1. Bundled binary (PyInstaller one-folder build)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        bundled = Path(meipass) / "ffmpeg" / "ffmpeg"
        if bundled.exists():
            return str(bundled)
        # Windows extension
        bundled_exe = bundled.with_suffix(".exe")
        if bundled_exe.exists():
            return str(bundled_exe)

    # 2. System PATH fallback
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    raise FileNotFoundError(
        "ffmpeg not found. Install ffmpeg and ensure it is on PATH, or use the bundled build."
    )


def concat_segments(segments: list[Path], output: Path) -> Path:
    """Assemble one or more video segments into a single output file.

    - 0 segments: raises ValueError.
    - 1 segment: copies the segment to output — no ffmpeg call.
    - N≥2 segments: runs ffmpeg concat demuxer (copy codec, no re-encode).

    Args:
        segments: Ordered list of segment Paths (seg_0.mp4, seg_1.mp4, …).
        output:   Target path for the assembled gameplay.mp4.

    Returns:
        Path to the assembled output file (always == output arg).

    Raises:
        ValueError: If segments list is empty.
        FileNotFoundError: If ffmpeg cannot be found for multi-segment concat.
        subprocess.CalledProcessError: If ffmpeg exits non-zero.
    """
    if not segments:
        raise ValueError("segments list must not be empty")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    # --- Single segment: copy, no ffmpeg ---
    if len(segments) == 1:
        src = Path(segments[0])
        shutil.copy2(src, output)
        logger.debug("concat_segments: single segment — copied %s → %s", src, output)
        return output

    # --- Multiple segments: ffmpeg concat demuxer ---
    ffmpeg_bin = _resolve_ffmpeg()

    # Build the concat list file: "file '/absolute/path/to/seg.mp4'"
    # Use POSIX paths to avoid ffmpeg parsing issues on Windows (ffmpeg accepts both)
    concat_lines = "\n".join(f"file '{Path(seg).as_posix()}'" for seg in segments)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as tmp_file:
        tmp_file.write(concat_lines)
        concat_list_path = Path(tmp_file.name)

    try:
        cmd = [
            ffmpeg_bin,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            "-y",  # overwrite output without asking
            str(output),
        ]
        logger.debug("concat_segments: running ffmpeg: %s", " ".join(cmd))
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        # Clean up the temp concat-list file
        try:
            concat_list_path.unlink()
        except OSError:
            pass

    return output
