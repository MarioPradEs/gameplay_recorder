"""Update checker for gameplay_recorder.

Provides two pure functions:
- compare_semver(a, b) -> int  — numeric semver comparison (-1, 0, 1)
- check_for_update(current_version) -> str | None  — GitHub Releases latest check

All exceptions are swallowed: the update banner must never crash the app.
"""

from __future__ import annotations

import json
from urllib.request import urlopen

from gameplay_recorder.config import GITHUB_REPO

_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def compare_semver(a: str, b: str) -> int:
    """Compare two semantic version strings numerically.

    Args:
        a: Version string, e.g. "1.10.0".
        b: Version string, e.g. "1.9.9".

    Returns:
        -1 if a < b, 0 if a == b, 1 if a > b.

    Comparison is numeric (not lexicographic) so "1.10.0" > "1.9.9".
    """
    a_parts = tuple(int(x) for x in a.split("."))
    b_parts = tuple(int(x) for x in b.split("."))
    if a_parts < b_parts:
        return -1
    if a_parts > b_parts:
        return 1
    return 0


def check_for_update(current_version: str) -> str | None:
    """Check GitHub Releases for a newer version.

    Args:
        current_version: The running app version, e.g. "0.1.0".

    Returns:
        The latest version string (e.g. "0.2.0") if a newer release exists,
        or ``None`` if up-to-date, unreachable, or the response is malformed.

    All exceptions are swallowed to keep the update banner non-blocking.
    """
    try:
        with urlopen(_RELEASES_URL) as response:
            data = json.loads(response.read())
        tag: str = data["tag_name"].lstrip("v")
        if compare_semver(tag, current_version) > 0:
            return tag
        return None
    except Exception:  # noqa: BLE001
        return None
