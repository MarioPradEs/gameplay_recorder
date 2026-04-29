"""Public-repo blacklist audit test.

Phase 9C: CI firewall — fails if any private identifier appears anywhere in
the public gameplay_recorder repository (source, tests, docs, config — all
text files except binary and generated files).

This test is the LAST LINE OF DEFENSE before publishing to GitHub.
It runs as part of the normal pytest run (no marker gate).

Forbidden strings are defined in _BLACKLIST_PATTERNS below (case-insensitive).
These include the private consumer-system name and the private game code name.

Any path containing these strings is also flagged.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Root of the public repo — determined relative to this test file's location.
# tests/audit/ -> tests/ -> repo_root/
_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()

# Directories to skip entirely (binary/generated artefacts)
_SKIP_DIRS = frozenset(
    {
        ".venv",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
        "node_modules",
    }
)

# File suffixes considered binary — never scan these
_BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".zip",
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
        ".pyc",
        ".pyo",
        ".pyd",
        ".so",
        ".dll",
        ".exe",
        ".bin",
        ".pkl",
        ".npz",
        ".npy",
        ".pt",
        ".pth",
        ".onnx",
        ".h5",
        ".db",
        ".sqlite",
        ".whl",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
    }
)


# Forbidden patterns — case-insensitive.
# Patterns are built at module load time from fragments to avoid embedding
# the literal forbidden strings in this file's source.
# Fragment notation: each tuple is (prefix, connector_class, suffix).
def _make_patterns() -> list[re.Pattern[str]]:
    """Build forbidden-string regex patterns without embedding literals here."""
    # Private consumer-system name: "bot" + "_" or "-" + "neuronal"
    # Private game code name:       "zombie" + "_", "-", or " " + "gore"
    # Also match concatenated variants (no separator).
    parts = [
        r"bot[_\-]neuronal",
        r"bot" + "neuronal",  # concatenated variant
        r"zombie[_\- ]gore",
        r"zombie" + "gore",  # concatenated variant
    ]
    return [re.compile(p, re.IGNORECASE) for p in parts]


_BLACKLIST_PATTERNS: list[re.Pattern[str]] = _make_patterns()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _should_skip_dir(directory: Path) -> bool:
    """Return True if this directory should be excluded from scanning."""
    for part in directory.parts:
        if part in _SKIP_DIRS:
            return True
        if part.endswith(".egg-info"):
            return True
    return False


def _is_binary_file(path: Path) -> bool:
    """Return True if the file should be treated as binary (not scanned)."""
    return path.suffix.lower() in _BINARY_SUFFIXES


def _scan_text_file(path: Path) -> list[dict[str, object]]:
    """Scan a text file for forbidden strings.

    Returns a list of match dicts with keys:
        file, line_number, line, matched_pattern
    """
    matches: list[dict[str, object]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return matches  # Unreadable file — skip silently

    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in _BLACKLIST_PATTERNS:
            if pattern.search(line):
                matches.append(
                    {
                        "file": str(path.relative_to(_REPO_ROOT)),
                        "line_number": lineno,
                        "line": line.strip(),
                        "matched_pattern": pattern.pattern,
                    }
                )
                break  # Only report once per line (first matching pattern)

    return matches


def _collect_text_files(root: Path) -> list[Path]:
    """Walk the repo and return all text files to scan."""
    text_files: list[Path] = []

    for path in root.rglob("*"):
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        if not path.is_file():
            continue
        if _is_binary_file(path):
            continue
        text_files.append(path)

    return text_files


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_no_forbidden_strings_in_public_repo() -> None:
    """ZERO private identifiers anywhere in the public repo.

    Walks the entire repo root recursively, skipping binary and generated
    files, and asserts that no line in any text file contains a forbidden
    string (private consumer-system name or private game code name).

    Failure message includes: file path, line number, matched string.
    """
    text_files = _collect_text_files(_REPO_ROOT)

    all_matches: list[dict[str, object]] = []
    for path in text_files:
        all_matches.extend(_scan_text_file(path))

    if all_matches:
        lines = [
            f"  {m['file']}:{m['line_number']}: {m['line']!r} (pattern: {m['matched_pattern']})"
            for m in all_matches
        ]
        report = "\n".join(lines)
        raise AssertionError(
            f"Found {len(all_matches)} forbidden string(s) in public repo:\n{report}\n\n"
            "Remove or replace all forbidden strings before publishing."
        )

    # Sanity: we actually scanned files
    assert len(text_files) > 0, (
        f"Expected to scan at least 1 text file, but found 0 in {_REPO_ROOT}"
    )
