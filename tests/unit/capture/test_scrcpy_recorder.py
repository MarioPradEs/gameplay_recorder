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

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
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
    """run() calls _graceful_stop() within 2s of requestInterruption().

    Spec: Scenario 'Graceful stop preserves video'.
    FakeProcess pattern: simulate the stop signal being received by the fake proc
    so that _graceful_stop completes and the recorder exits cleanly.
    os.kill is patched to avoid real Windows signal delivery to a fake PID.
    """
    import time

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()

    def _fake_os_kill(pid, sig):
        # Simulate CTRL_BREAK_EVENT being received — fake proc stops
        fake_proc._terminated = True
        fake_proc.returncode = 0

    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
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
        "_graceful_stop() must be called within 2s of requestInterruption()"
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
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill"),  # prevent real signal delivery
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

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
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

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
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

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
        patch(
            "gameplay_recorder.capture.scrcpy_recorder._validate_mp4",
            return_value=(True, None),
        ),
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
    import time

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="17d4994b", output_path=Path("/tmp/gameplay.mp4"))

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 1024

        with patch("gameplay_recorder.capture.scrcpy_recorder.logger") as mock_logger:
            recorder.start()
            time.sleep(0.15)
            recorder.requestInterruption()
            recorder.wait(3000)

        # At least one info call was made during the lifecycle
        assert mock_logger.info.called, "logger.info() must be called during recording lifecycle"


# ---------------------------------------------------------------------------
# Phase 4.1 — check_host_free_space (RED)
# ---------------------------------------------------------------------------


def test_check_host_free_space_returns_none_above_threshold():
    """check_host_free_space() calls shutil.disk_usage and returns None when free space >= 1 GB.

    Spec: Scenario 'Sufficient storage' — recording can proceed without warning.
    None return means OK. disk_usage MUST be called — proves the stub was replaced.
    """
    from gameplay_recorder.capture.scrcpy_recorder import check_host_free_space

    # 2 GB free — well above the 1 GB threshold
    two_gb = 2 * 1024**3
    fake_usage = type("DiskUsage", (), {"free": two_gb})()

    with patch(
        "gameplay_recorder.capture.scrcpy_recorder.shutil.disk_usage", return_value=fake_usage
    ) as mock_du:
        result = check_host_free_space(Path("/some/output/dir"))

    assert mock_du.called, "shutil.disk_usage must be called — stub still active if this fails"
    assert result is None, "Must return None (OK) when free space >= 1 GB"


def test_check_host_free_space_returns_message_below_threshold():
    """check_host_free_space() returns an error string when free space < 1 GB.

    Spec: Scenario 'Insufficient storage' — message must contain '<1 GB' and the dir.
    """

    from gameplay_recorder.capture.scrcpy_recorder import check_host_free_space

    # 500 MB free — below the 1 GB threshold
    half_gb = 512 * 1024**2
    fake_usage = type("DiskUsage", (), {"free": half_gb})()
    output_dir = Path("/some/output/dir")

    with patch(
        "gameplay_recorder.capture.scrcpy_recorder.shutil.disk_usage", return_value=fake_usage
    ):
        result = check_host_free_space(output_dir)

    assert result is not None, "Must return an error string when free space < 1 GB"
    assert "1 GB" in result, f"Error message must mention '1 GB': {result!r}"
    assert str(output_dir) in result, f"Error message must include the output dir path: {result!r}"


def test_check_host_free_space_returns_none_on_oserror():
    """check_host_free_space() attempts disk_usage, catches OSError and returns None.

    Design: defensive fallback — OSError means we can't determine free space,
    so we allow recording to proceed (None = OK) rather than blocking the user.
    disk_usage MUST be called (and raise) — proves the stub was replaced.
    """
    from gameplay_recorder.capture.scrcpy_recorder import check_host_free_space

    with patch(
        "gameplay_recorder.capture.scrcpy_recorder.shutil.disk_usage",
        side_effect=OSError("Permission denied"),
    ) as mock_du:
        result = check_host_free_space(Path("/restricted/dir"))

    assert mock_du.called, "shutil.disk_usage must be called — stub still active if this fails"
    assert result is None, "Must return None (defensive) on OSError — do not block recording"


def test_check_host_free_space_falls_back_to_parent_dir_if_dir_missing():
    """check_host_free_space() uses parent dir when the output dir does not exist yet.

    Spec/Design: output_dir may not be created yet at check time (session_dir is
    created lazily). Fall back to parent so disk_usage doesn't raise FileNotFoundError.
    """

    from gameplay_recorder.capture.scrcpy_recorder import check_host_free_space

    two_gb = 2 * 1024**3
    fake_usage = type("DiskUsage", (), {"free": two_gb})()

    # A path whose parent is a real dir but the dir itself does not exist
    nonexistent_dir = Path("/nonexistent/session/dir/that/does/not/exist")

    called_with = []

    def _fake_disk_usage(path):
        called_with.append(path)
        return fake_usage

    with (
        patch(
            "gameplay_recorder.capture.scrcpy_recorder.shutil.disk_usage",
            side_effect=_fake_disk_usage,
        ),
        patch("gameplay_recorder.capture.scrcpy_recorder.Path.exists", return_value=False),
    ):
        result = check_host_free_space(nonexistent_dir)

    assert result is None, "Must return None when parent dir has enough free space"
    assert len(called_with) >= 1, "disk_usage must be called (on some path)"
    # The fallback path must NOT be the missing dir itself — it must be an ancestor
    assert called_with[0] != nonexistent_dir, (
        f"disk_usage must NOT be called with the nonexistent dir {nonexistent_dir!r}; "
        f"got {called_with[0]!r}"
    )


# ---------------------------------------------------------------------------
# Phase 1.1 — Graceful shutdown: spawn flags + time-limit (RED)
# ---------------------------------------------------------------------------


def test_spawn_uses_create_new_process_group_on_windows():
    """_spawn_scrcpy() passes CREATE_NEW_PROCESS_GROUP in creationflags on Windows.

    Spec: Windows spawn must use CREATE_NEW_PROCESS_GROUP so CTRL_BREAK_EVENT
    can be delivered later. Without it, signal delivery fails silently.
    """
    import subprocess as _subprocess

    from gameplay_recorder.capture.scrcpy_recorder import _spawn_scrcpy

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder.sys") as mock_sys,
        patch("gameplay_recorder.capture.scrcpy_recorder.subprocess.Popen") as mock_popen,
    ):
        mock_sys.platform = "win32"
        mock_sys._MEIPASS = None
        mock_popen.return_value = MagicMock(pid=12345)
        _spawn_scrcpy("abc123", Path("/tmp/gameplay.mp4"))

    kwargs = mock_popen.call_args[1]
    assert "creationflags" in kwargs, "creationflags must be passed on Windows"
    assert kwargs["creationflags"] & _subprocess.CREATE_NEW_PROCESS_GROUP, (
        "CREATE_NEW_PROCESS_GROUP must be set in creationflags on Windows"
    )


def test_spawn_no_creationflags_on_non_windows():
    """_spawn_scrcpy() does NOT pass creationflags on non-Windows platforms.

    Spec: Linux/macOS use default Popen (no creationflags needed — SIGTERM works).
    """
    from gameplay_recorder.capture.scrcpy_recorder import _spawn_scrcpy

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder.sys") as mock_sys,
        patch("gameplay_recorder.capture.scrcpy_recorder.subprocess.Popen") as mock_popen,
    ):
        mock_sys.platform = "linux"
        mock_sys._MEIPASS = None
        mock_popen.return_value = MagicMock(pid=12345)
        _spawn_scrcpy("abc123", Path("/tmp/gameplay.mp4"))

    kwargs = mock_popen.call_args[1]
    # Either creationflags is absent, or it is 0 (no flags set)
    flag_value = kwargs.get("creationflags", 0)
    assert flag_value == 0, f"creationflags must be absent or 0 on non-Windows, got {flag_value!r}"


def test_spawn_includes_time_limit_7200():
    """_spawn_scrcpy() includes --time-limit=7200 in the scrcpy command.

    Spec: 2-hour safety cap so scrcpy self-finalizes the mp4 even if signal
    delivery fails — ensures the moov atom is always written.
    """
    from gameplay_recorder.capture.scrcpy_recorder import _spawn_scrcpy

    with patch("gameplay_recorder.capture.scrcpy_recorder.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=12345)
        _spawn_scrcpy("abc123", Path("/tmp/gameplay.mp4"))

    cmd = mock_popen.call_args[0][0]
    cmd_str = " ".join(str(c) for c in cmd)
    assert "time-limit" in cmd_str and "7200" in cmd_str, (
        f"--time-limit=7200 (or --time-limit 7200) must appear in command: {cmd_str!r}"
    )


# ---------------------------------------------------------------------------
# Phase 1.1 — Graceful shutdown: _graceful_stop signal routing (RED)
# ---------------------------------------------------------------------------


def _make_recorder_with_mock_proc(mock_proc):
    """Helper: build a ScrcpyRecorder whose _spawn_scrcpy returns mock_proc."""
    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    recorder = ScrcpyRecorder(serial="abc123", output_path=Path("/tmp/gameplay.mp4"))
    # Attach proc directly so we can call _graceful_stop without run()
    recorder.proc = mock_proc
    return recorder


def test_graceful_stop_sends_ctrl_break_on_windows():
    """_graceful_stop() sends os.kill(pid, CTRL_BREAK_EVENT) on Windows.

    Spec: Windows stop signal must be CTRL_BREAK_EVENT — terminate() sends
    TerminateProcess (hard kill) which prevents moov atom flush.
    """
    import signal as _signal

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    mock_proc = MagicMock()
    mock_proc.pid = 42
    mock_proc.wait.return_value = 0  # exits cleanly

    recorder = ScrcpyRecorder(serial="abc123", output_path=Path("/tmp/gameplay.mp4"))

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder.sys") as mock_sys,
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill") as mock_kill,
    ):
        mock_sys.platform = "win32"
        recorder._graceful_stop(mock_proc)

    mock_kill.assert_called_once_with(42, _signal.CTRL_BREAK_EVENT)


def test_graceful_stop_uses_terminate_on_linux():
    """_graceful_stop() calls proc.terminate() on Linux (not os.kill).

    Spec: SIGTERM via terminate() is the correct stop signal on Linux.
    """
    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    mock_proc = MagicMock()
    mock_proc.pid = 42
    mock_proc.wait.return_value = 0  # exits cleanly

    recorder = ScrcpyRecorder(serial="abc123", output_path=Path("/tmp/gameplay.mp4"))

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder.sys") as mock_sys,
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill") as mock_kill,
    ):
        mock_sys.platform = "linux"
        recorder._graceful_stop(mock_proc)

    mock_proc.terminate.assert_called_once()
    mock_kill.assert_not_called()


def test_graceful_stop_uses_terminate_on_macos():
    """_graceful_stop() calls proc.terminate() on macOS (not os.kill).

    Spec: SIGTERM via terminate() is the correct stop signal on macOS.
    """
    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    mock_proc = MagicMock()
    mock_proc.pid = 42
    mock_proc.wait.return_value = 0  # exits cleanly

    recorder = ScrcpyRecorder(serial="abc123", output_path=Path("/tmp/gameplay.mp4"))

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder.sys") as mock_sys,
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill") as mock_kill,
    ):
        mock_sys.platform = "darwin"
        recorder._graceful_stop(mock_proc)

    mock_proc.terminate.assert_called_once()
    mock_kill.assert_not_called()


def test_graceful_stop_escalates_to_kill_after_grace_period():
    """_graceful_stop() calls proc.kill() and sets _aborted=True when proc.wait() times out.

    Spec: 5s grace period; if exceeded → hard kill + _aborted flag for downstream
    validation routing (Phase 2).
    """
    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    mock_proc = MagicMock()
    mock_proc.pid = 42
    mock_proc.wait.side_effect = subprocess.TimeoutExpired("scrcpy", 5)

    recorder = ScrcpyRecorder(serial="abc123", output_path=Path("/tmp/gameplay.mp4"))

    with patch("gameplay_recorder.capture.scrcpy_recorder.sys") as mock_sys:
        mock_sys.platform = "linux"
        recorder._graceful_stop(mock_proc)

    mock_proc.kill.assert_called_once()
    assert recorder._aborted is True, (
        "_aborted must be True after grace period exceeded — signals corrupt mp4 risk"
    )


def test_graceful_stop_no_kill_when_proc_exits_cleanly():
    """_graceful_stop() does NOT call proc.kill() when proc exits within grace period.

    Spec: Normal stop — proc exits within 5s, no hard kill, _aborted stays False.
    """
    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    mock_proc = MagicMock()
    mock_proc.pid = 42
    mock_proc.wait.return_value = 0  # exits cleanly within grace

    recorder = ScrcpyRecorder(serial="abc123", output_path=Path("/tmp/gameplay.mp4"))

    with patch("gameplay_recorder.capture.scrcpy_recorder.sys") as mock_sys:
        mock_sys.platform = "linux"
        recorder._graceful_stop(mock_proc)

    mock_proc.kill.assert_not_called()
    assert recorder._aborted is False, (
        "_aborted must remain False when proc exits cleanly within grace period"
    )


# ---------------------------------------------------------------------------
# Phase 2.2 — mp4 validation wiring in ScrcpyRecorder.run()
# ---------------------------------------------------------------------------


def test_validation_warning_set_when_mp4_invalid(tmp_path):
    """ScrcpyRecorder._validation_warning is set when mp4 lacks moov atom.

    Spec: Phase 2 — after run() completes, _validation_warning contains reason
    string when the output mp4 has no moov atom.
    """
    import time

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    # Create an mp4 file with NO moov atom (just mdat-like bytes)
    bad_mp4 = tmp_path / "gameplay.mp4"
    bad_mp4.write_bytes(b"\x00\x00\x00\x20" + b"ftypisom" + b"\x00" * 100 + b"mdat" + b"\x00" * 200)

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="abc123", output_path=bad_mp4)

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
    ):
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()
        recorder.wait(3000)

    assert recorder._validation_warning is not None, (
        "_validation_warning must be set when mp4 has no moov atom"
    )
    assert "moov" in recorder._validation_warning.lower(), (
        f"_validation_warning must mention 'moov': {recorder._validation_warning!r}"
    )


def test_validation_warning_none_when_mp4_valid(tmp_path):
    """ScrcpyRecorder._validation_warning stays None when mp4 has moov atom.

    Spec: Phase 2 — _validation_warning is None when mp4 validation passes.
    """
    import time

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    # Create an mp4 file WITH moov atom
    good_mp4 = tmp_path / "gameplay.mp4"
    good_mp4.write_bytes(
        b"\x00\x00\x00\x20" + b"ftypisom" + b"\x00" * 100 + b"moov" + b"\x00" * 200
    )

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="abc123", output_path=good_mp4)

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
    ):
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()
        recorder.wait(3000)

    assert recorder._validation_warning is None, (
        "_validation_warning must remain None when mp4 contains moov atom"
    )


def test_validation_warning_signal_emitted_on_invalid_mp4(tmp_path):
    """ScrcpyRecorder.validation_warning signal fires when validation fails.

    Spec: Phase 2 — validation_warning(str) signal is emitted with the reason
    string when the output mp4 has no moov atom.
    """
    import time

    from PySide6.QtCore import Qt

    from gameplay_recorder.capture.scrcpy_recorder import ScrcpyRecorder

    # Create an mp4 file with NO moov atom
    bad_mp4 = tmp_path / "gameplay.mp4"
    bad_mp4.write_bytes(b"\x00\x00\x00\x20" + b"ftypisom" + b"\x00" * 100 + b"mdat" + b"\x00" * 200)

    fake_proc = _FakeProcess()
    recorder = ScrcpyRecorder(serial="abc123", output_path=bad_mp4)

    warnings_received = []
    recorder.validation_warning.connect(warnings_received.append, Qt.DirectConnection)

    def _fake_os_kill(pid, sig):
        fake_proc._terminated = True
        fake_proc.returncode = 0

    with (
        patch("gameplay_recorder.capture.scrcpy_recorder._spawn_scrcpy", return_value=fake_proc),
        patch("gameplay_recorder.capture.scrcpy_recorder.os.kill", side_effect=_fake_os_kill),
    ):
        recorder.start()
        time.sleep(0.15)
        recorder.requestInterruption()
        recorder.wait(3000)

    assert len(warnings_received) >= 1, (
        "validation_warning signal must be emitted when mp4 has no moov atom"
    )
    assert "moov" in warnings_received[0].lower(), (
        f"Signal payload must mention 'moov': {warnings_received[0]!r}"
    )
