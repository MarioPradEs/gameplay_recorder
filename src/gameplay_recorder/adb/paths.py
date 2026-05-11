"""Resolve the path to the adb executable.

In production (PyInstaller bundle), adb is bundled inside
resources/scrcpy/ via the spec file's `datas` entry. We must
NOT rely on the user having adb on their system PATH.

In development, the same path layout is reproduced under the repo
root by `scripts/setup_scrcpy.ps1`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Return the root directory containing 'resources/scrcpy/'.

    PyInstaller bundle: sys._MEIPASS.
    Dev: repo root (4 levels up from this file: src/gameplay_recorder/adb/paths.py).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    # paths.py → adb/ → gameplay_recorder/ → src/ → repo_root
    return Path(__file__).resolve().parent.parent.parent.parent


def adb_path() -> Path:
    """Return the absolute path to the adb executable to use.

    Resolution order:
    1. If running from a PyInstaller bundle (sys.frozen + sys._MEIPASS),
       return <_MEIPASS>/resources/scrcpy/adb.exe (or 'adb' on non-Windows).
    2. Otherwise, return <repo_root>/resources/scrcpy/adb.exe (dev mode,
       requires `scripts/setup_scrcpy.ps1` to have been run).
    3. If the resolved path does not exist, raise FileNotFoundError with
       a clear actionable message so the user knows to run setup_scrcpy.ps1.

    On non-Windows platforms, use 'adb' (no .exe extension).

    Raises:
        FileNotFoundError: If the binary is not present at the expected
            bundled location.
    """
    binary = "adb.exe" if sys.platform == "win32" else "adb"
    candidate = _bundle_root() / "resources" / "scrcpy" / binary
    if not candidate.is_file():
        raise FileNotFoundError(
            f"adb executable not found at {candidate}. "
            f"In dev: run scripts/setup_scrcpy.ps1 to install scrcpy + adb. "
            f"In production: the PyInstaller bundle is missing resources/scrcpy/."
        )
    return candidate
