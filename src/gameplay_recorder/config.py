"""Application-level constants and configuration defaults."""

from pathlib import Path

# Default directory where session ZIPs are saved
DEFAULT_OUTPUT_DIR: Path = Path.home() / "Documents" / "gameplay-recordings"

# Interval in seconds between consecutive screenshots
SCREENSHOT_INTERVAL_S: int = 5

# Duration in seconds per video segment (Android hard limit is 180s; we use 170s for safety)
SEGMENT_DURATION_S: int = 170

# GitHub repository slug (used by the auto-update checker)
GITHUB_REPO: str = "MarioPradEs/gameplay_recorder"
