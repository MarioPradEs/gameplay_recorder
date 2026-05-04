"""Unit tests for ScrcpyRecorder.

TDD Phase 2 (RED) — written BEFORE production code exists.
All subprocess calls are mocked — no real devices or processes.

Spec: gameplay-recorder-scrcpy-pivot / scrcpy Video Capture + Free-Space Pre-Check
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Fake subprocess.Popen that stays 'running' until terminate() is called."""

    def __init__(self):
        self._terminated = False
        self.pid = 99999
        self.returncode = None

    def poll(self):
        return 0 if self._terminated else None

    def wait(self, timeout=None):
        if self._terminated:
            return 0
        raise subprocess.TimeoutExpired("scrcpy", timeout)

    def terminate(self):
        self._terminated = True
        self.returncode = -15

    def kill(self):
        self._terminated = True
        self.returncode = -9


# ---------------------------------------------------------------------------
# Phase 2.1 — Constructor
# ---------------------------------------------------------------------------


def test_constructor_stores_serial_and_output_path():
    """ScrcpyRecorder stores serial and output_path on construction.

    Spec: ScrcpyRecorder(serial, output_path, parent=None)
    """
    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    assert recorder._serial == "17d4994b"
    assert recorder._output_path == Path("/tmp/gameplay.mp4")


# ---------------------------------------------------------------------------
# Phase 2.1 — _resolve_scrcpy
# ---------------------------------------------------------------------------


def test_resolve_scrcpy_finds_meipass_first():
    """_resolve_scrcpy() uses sys._MEIPASS/scrcpy.exe when bundled.

    Design: mirrors _resolve_adb() / _resolve_ffmpeg() pattern.
    """
    import tempfile

    from gameplay_recorder.capture.scrcpy_recorder import _resolve_scrcpy

    with tempfile.TemporaryDirectory() as tmpdir:
        scrcpy_exe = Path(tmpdir) / "scrcpy.exe"
        scrcpy_exe.touch()

        with patch.object(sys, "_MEIPASS", tmpdir, create=True):
            result = _resolve_scrcpy()

    assert str(scrcpy_exe) == result


def test_resolve_scrcpy_falls_back_to_shutil_which():
    """_resolve_scrcpy() falls back to shutil.which when no bundle present.

    Design: returns path from PATH or 'scrcpy' literal as last resort.
    """
    from gameplay_recorder.capture.scrcpy_recorder import _resolve_scrcpy

    # Ensure _MEIPASS is not set
    original = getattr(sys, "_MEIPASS", None)
    if hasattr(sys, "_MEIPASS"):
        del sys._MEIPASS
    try:
        with patch(
            "gameplay_recorder.capture.scrcpy_recorder.shutil.which", return_value="/usr/bin/scrcpy"
        ):
            result = _resolve_scrcpy()
        assert result == "/usr/bin/scrcpy"
    finally:
        if original is not None:
            sys._MEIPASS = original


# ---------------------------------------------------------------------------
# Phase 2.1 — _spawn_scrcpy
# ---------------------------------------------------------------------------


def test_spawn_scrcpy_builds_correct_command_line():
    """_spawn_scrcpy() passes --serial, --record, --no-playback, --no-audio to Popen.

    Spec: scrcpy --serial <SERIAL> --record <output_path> --no-playback --no-audio
    All 4 key arguments must be present in the command.
    """
    from gameplay_recorder.capture.scrcpy_recorder import _spawn_scrcpy

    with patch("gameplay_recorder.capture.scrcpy_recorder.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=12345)
        _spawn_scrcpy("17d4994b", Path("/tmp/gameplay.mp4"))

    cmd = mock_popen.call_args[0][0]
    cmd_str = " ".join(str(c) for c in cmd)

    assert "--serial" in cmd_str
    assert "17d4994b" in cmd_str
    assert "--record" in cmd_str
    assert "gameplay.mp4" in cmd_str


def test_spawn_scrcpy_includes_no_audio_flag():
    """_spawn_scrcpy() always includes --no-audio flag.

    Spec: Scenario 'Audio is disabled' — mp4 must have zero audio tracks.
    """
    from gameplay_recorder.capture.scrcpy_recorder import _spawn_scrcpy

    with patch("gameplay_recorder.capture.scrcpy_recorder.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=12345)
        _spawn_scrcpy("17d4994b", Path("/tmp/gameplay.mp4"))

    cmd = mock_popen.call_args[0][0]
    assert "--no-audio" in cmd


def test_spawn_scrcpy_includes_no_playback_flag():
    """_spawn_scrcpy() always includes --no-playback flag (scrcpy 3.x, replaces --no-display).

    scrcpy 3.x gotcha: --no-display was removed, --no-playback is the replacement.
    """
    from gameplay_recorder.capture.scrcpy_recorder import _spawn_scrcpy

    with patch("gameplay_recorder.capture.scrcpy_recorder.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=12345)
        _spawn_scrcpy("17d4994b", Path("/tmp/gameplay.mp4"))

    cmd = mock_popen.call_args[0][0]
    assert "--no-playback" in cmd


# ---------------------------------------------------------------------------
# Phase 2.1 — ScrcpyRecorder.run() lifecycle
# ---------------------------------------------------------------------------


def test_run_emits_recording_started_after_proc_starts():
    """run() emits recording_started signal after scrcpy process is alive.

    Design: recording_started fires once, after process confirmed running.
    Uses Qt.DirectConnection so the slot runs in the emitting thread,
    bypassing the need for a running event loop in the test.
    """
    import time

    from PySide6.QtCore import Qt

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    started_count = [0]

    def _on_started():
        started_count[0] += 1

    recorder.recording_started.connect(_on_started, Qt.DirectConnection)

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 1024
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()
        recorder.wait(2000)  # ms — Qt wait

    assert started_count[0] >= 1, "recording_started must be emitted at least once"


def test_run_terminates_on_interruption_within_2s():
    """run() calls terminate() within 2s of requestInterruption().

    Spec: Scenario 'Graceful stop preserves video'.
    FakeProcess pattern: terminate() sets _terminated, wait() returns.
    """
    import time

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 1024
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if fake_proc._terminated:
                break
            time.sleep(0.05)

        recorder.wait(3000)

    assert fake_proc._terminated, (
        "proc.terminate() must be called within 2s of requestInterruption()"
    )


def test_run_escalates_to_kill_after_terminate_timeout():
    """run() escalates to proc.kill() after 5s if terminate() doesn't stop the process.

    Spec: Scenario 'Forced kill after timeout'.
    """
    import time

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    class _StubbornProcess(_FakeProcess):
        def __init__(self):
            super().__init__()
            self._kill_called = False

        def terminate(self):
            # SIGTERM ignored — process stays alive
            self.returncode = -15

        def wait(self, timeout=None):
            if self._terminated:
                return 0
            raise subprocess.TimeoutExpired("scrcpy", timeout)

        def kill(self):
            self._terminated = True
            self._kill_called = True
            self.returncode = -9

    stubborn = _StubbornProcess()
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=stubborn),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 1024
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if stubborn._kill_called:
                break
            time.sleep(0.05)

        recorder.wait(4000)

    assert stubborn._kill_called, "proc.kill() must be called when terminate() doesn't stop in 5s"


def test_run_emits_recording_error_when_output_file_missing():
    """run() emits recording_error when gameplay.mp4 doesn't exist after stop.

    Spec: Scenario 'Recording fails to start' — no truncated file left behind.
    Uses Qt.DirectConnection for cross-thread signal delivery without event loop.
    """
    import time

    from PySide6.QtCore import Qt

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    errors = []
    recorder.recording_error.connect(errors.append, Qt.DirectConnection)

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("pathlib.Path.exists", return_value=False),
    ):
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()
        recorder.wait(3000)

    assert len(errors) >= 1, "recording_error must be emitted when output file is missing"


def test_run_emits_recording_error_when_output_file_is_empty():
    """run() emits recording_error when gameplay.mp4 exists but is zero bytes.

    Spec: Scenario 'Recording fails to start' — zero-byte file is invalid.
    Uses Qt.DirectConnection for cross-thread signal delivery without event loop.
    """
    import time

    from PySide6.QtCore import Qt

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    errors = []
    recorder.recording_error.connect(errors.append, Qt.DirectConnection)

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 0
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()
        recorder.wait(3000)

    assert len(errors) >= 1, "recording_error must be emitted when output file is zero bytes"


def test_run_emits_recording_finished_with_path_on_success():
    """run() emits recording_finished(Path) when gameplay.mp4 is valid.

    Spec: Scenario 'Single-file recording produced' — finished emits the output path.
    Uses Qt.DirectConnection for cross-thread signal delivery without event loop.
    """
    import time

    from PySide6.QtCore import Qt

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()
    output_path = Path("/tmp/gameplay.mp4")
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=output_path)

    finished_paths = []
    recorder.recording_finished.connect(finished_paths.append, Qt.DirectConnection)

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 2048
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()
        recorder.wait(3000)

    assert len(finished_paths) >= 1, "recording_finished must be emitted on success"
    assert finished_paths[0] == output_path


def test_run_logs_lifecycle_at_info_level():
    """run() emits INFO-level log messages at start and stop.

    Spec: design decision — lifecycle events logged at INFO level.
    """
    import logging
    import time

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 1024
        import logging

        with patch("gameplay_recorder.capture.scrcpy_recorder.logger") as mock_logger:
            recorder.start()
            time.sleep(0.15)
            recorder.requestInterruption()
            recorder.wait(3000)

        # At least one info call was made during the lifecycle
        assert mock_logger.info.called, "logger.info() must be called during recording lifecycle"
