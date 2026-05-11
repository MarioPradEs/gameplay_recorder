"""Tests for adb_path() helper — resolves the bundled adb executable path."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def test_adb_path_returns_meipass_path_when_frozen(tmp_path):
    """When running from a PyInstaller bundle, adb_path uses sys._MEIPASS."""
    fake_meipass = tmp_path / "bundle"
    (fake_meipass / "resources" / "scrcpy").mkdir(parents=True)
    fake_adb = fake_meipass / "resources" / "scrcpy" / "adb.exe"
    fake_adb.write_text("")  # touch

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "_MEIPASS", str(fake_meipass), create=True),
        patch("sys.platform", "win32"),
    ):
        import importlib
        import gameplay_recorder.adb.paths as paths_mod

        importlib.reload(paths_mod)
        result = paths_mod.adb_path()
        assert result == fake_adb


def test_adb_path_returns_repo_relative_path_in_dev(tmp_path, monkeypatch):
    """When running from source (not frozen), adb_path uses repo-relative path.

    We mock _bundle_root() to return a fake repo root rather than trying to
    redirect __file__ (which doesn't survive importlib.reload cleanly).
    """
    fake_repo = tmp_path / "repo"
    (fake_repo / "resources" / "scrcpy").mkdir(parents=True)
    fake_adb = fake_repo / "resources" / "scrcpy" / "adb.exe"
    fake_adb.write_text("")

    # Ensure 'frozen' is not present so _bundle_root falls into the dev branch
    monkeypatch.delattr(sys, "frozen", raising=False)

    import gameplay_recorder.adb.paths as paths_mod

    with (
        patch.object(paths_mod, "_bundle_root", return_value=fake_repo),
        patch("sys.platform", "win32"),
    ):
        result = paths_mod.adb_path()
        assert result == fake_adb


def test_adb_path_raises_when_executable_missing(tmp_path):
    """If the resolved adb path does not exist, raise FileNotFoundError with
    a clear actionable message (mentioning setup_scrcpy.ps1 or scrcpy)."""
    fake_meipass = tmp_path / "empty"
    fake_meipass.mkdir()

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "_MEIPASS", str(fake_meipass), create=True),
        patch("sys.platform", "win32"),
    ):
        import importlib
        import gameplay_recorder.adb.paths as paths_mod

        importlib.reload(paths_mod)
        with pytest.raises(FileNotFoundError) as exc_info:
            paths_mod.adb_path()
        assert (
            "scrcpy" in str(exc_info.value).lower() or "setup_scrcpy" in str(exc_info.value).lower()
        )


def test_adb_path_uses_no_extension_on_non_windows(tmp_path):
    """On macOS/Linux, the binary is just 'adb' (no .exe)."""
    fake_meipass = tmp_path / "bundle"
    (fake_meipass / "resources" / "scrcpy").mkdir(parents=True)
    fake_adb = fake_meipass / "resources" / "scrcpy" / "adb"
    fake_adb.write_text("")

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "_MEIPASS", str(fake_meipass), create=True),
        patch("sys.platform", "darwin"),
    ):
        import importlib
        import gameplay_recorder.adb.paths as paths_mod

        importlib.reload(paths_mod)
        result = paths_mod.adb_path()
        assert result == fake_adb
        assert ".exe" not in str(result)
