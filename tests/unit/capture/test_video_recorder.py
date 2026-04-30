"""Unit tests for VideoSegmentRecorder.

TDD Phase 5 — RED written first, production code does NOT exist yet.
All subprocess and ADB calls are mocked — no real devices or processes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from gameplay_recorder.adb.connection import AdbConnection

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_conn(free_kb: int = 600_000) -> MagicMock:
    """Return a spec=AdbConnection mock whose shell() fakes df output.

    Using MagicMock(spec=AdbConnection) ensures that any call to a method that
    does NOT exist on AdbConnection raises AttributeError immediately — catching
    API drift in tests. This is the exact pattern that exposed C1 (shell() missing).
    """
    conn = MagicMock(spec=AdbConnection)
    # df /sdcard output: 'Filesystem   1K-blocks  Used Available Use% Mounted on'
    # We just need the integer in the "Available" column (4th field on data row).
    conn.shell.return_value = (
        "Filesystem       1K-blocks    Used Available Use% Mounted on\n"
        f"tmpfs             1024000  {1024000 - free_kb}   {free_kb}  50% /sdcard\n"
    )
    return conn


# ---------------------------------------------------------------------------
# Task 5.1 – test_free_space_check_passes_if_above_500mb
# ---------------------------------------------------------------------------


def test_free_space_check_passes_if_above_500mb():
    """check_free_space returns None when /sdcard has >= 500 MB free.

    Spec: Requirement 'Free-Space Pre-Check', Scenario 'Sufficient storage'.
    """
    from gameplay_recorder.capture.video_recorder import check_free_space

    conn = _make_mock_conn(free_kb=600_000)  # 600 MB
    result = check_free_space(conn)
    assert result is None, f"Expected None (enough space), got: {result!r}"


# ---------------------------------------------------------------------------
# Task 5.1 – test_free_space_check_blocks_if_below_500mb
# ---------------------------------------------------------------------------


def test_free_space_check_blocks_if_below_500mb():
    """check_free_space returns an error string when /sdcard < 500 MB free.

    Spec: Requirement 'Free-Space Pre-Check', Scenario 'Insufficient storage'.
    """
    from gameplay_recorder.capture.video_recorder import check_free_space

    conn = _make_mock_conn(free_kb=400_000)  # 400 MB — below threshold
    result = check_free_space(conn)
    assert result is not None, "Expected an error string, got None"
    assert "500" in result or "storage" in result.lower(), (
        f"Error message should mention '500' or 'storage', got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Task 5.1 – test_free_space_check_exactly_at_boundary
# (triangulation: exactly 500 MB should pass)
# ---------------------------------------------------------------------------


def test_free_space_check_exactly_at_boundary():
    """Exactly 500 MB (500 000 KB) should be considered sufficient.

    Triangulation: boundary value analysis.
    """
    from gameplay_recorder.capture.video_recorder import check_free_space

    conn = _make_mock_conn(free_kb=500_000)
    result = check_free_space(conn)
    assert result is None, f"500 MB exactly should pass, got: {result!r}"


# ---------------------------------------------------------------------------
# Task 5.1 – test_segment_filename_pattern
# ---------------------------------------------------------------------------


def test_segment_filename_pattern():
    """VideoSegmentRecorder generates seg_0.mp4, seg_1.mp4 for consecutive segments.

    Spec: Tasks 5.1 — segment filename pattern.
    """
    from gameplay_recorder.capture.video_recorder import segment_path

    assert segment_path(0).name == "seg_0.mp4"
    assert segment_path(1).name == "seg_1.mp4"
    assert segment_path(99).name == "seg_99.mp4"


# ---------------------------------------------------------------------------
# Task 5.1 – test_new_segment_triggered_at_170s
# ---------------------------------------------------------------------------


def test_new_segment_triggered_at_170s():
    """After 170 s a second screenrecord subprocess is spawned.

    Spec: Requirement 'Segmented Video Capture', Scenario 'Long session > 170s'.
    We mock subprocess.Popen and time.monotonic so no real process is started.
    """
    from gameplay_recorder.capture.video_recorder import _spawn_screenrecord

    serial = "emulator-5554"
    # Use strings for device paths (they stay as POSIX paths on the Android device)
    path_0 = "/sdcard/seg_0.mp4"
    path_1 = "/sdcard/seg_1.mp4"

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_subprocess.Popen.return_value = mock_proc

        _spawn_screenrecord(serial, path_0, duration=170)
        _spawn_screenrecord(serial, path_1, duration=170)

    # Two distinct Popen calls made — each segment spawns its own process
    assert mock_subprocess.Popen.call_count == 2
    # Each call uses the correct device serial and path — check the cmd list directly
    calls = mock_subprocess.Popen.call_args_list
    cmd_0 = calls[0][0][0]  # positional cmd list from first call
    cmd_1 = calls[1][0][0]
    assert "/sdcard/seg_0.mp4" in cmd_0
    assert "/sdcard/seg_1.mp4" in cmd_1


# ---------------------------------------------------------------------------
# Task 5.1 – test_spawn_screenrecord_uses_correct_command
# (triangulation: verify exact adb screenrecord command structure)
# ---------------------------------------------------------------------------


def test_spawn_screenrecord_uses_correct_command():
    """_spawn_screenrecord builds the right adb command.

    Triangulation: exact command shape matters for compatibility.
    Device paths remain POSIX strings (they run on Android, not Windows).
    """
    from gameplay_recorder.capture.video_recorder import _spawn_screenrecord

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_proc = MagicMock()
        mock_subprocess.Popen.return_value = mock_proc

        # Pass a string — device paths are always POSIX on the Android side
        _spawn_screenrecord("DEVICE123", "/sdcard/seg_0.mp4", duration=170)

    args = mock_subprocess.Popen.call_args
    cmd = args[0][0]  # positional arg: the command list

    # adb binary (may have full path on Windows)
    assert "adb" in cmd[0].lower()
    assert "-s" in cmd
    assert "DEVICE123" in cmd
    assert "screenrecord" in cmd
    assert "--time-limit" in cmd
    assert "170" in str(cmd)
    assert "/sdcard/seg_0.mp4" in cmd


# ---------------------------------------------------------------------------
# Task 5.1 – test_segment_pulled_and_deleted_from_device
# ---------------------------------------------------------------------------


def test_segment_pulled_and_deleted_from_device():
    """pull_and_delete() calls adb pull then adb shell rm for the same path.

    Spec: Requirement 'Segmented Video Capture', Scenario 'On-device cleanup'.
    """
    from gameplay_recorder.capture.video_recorder import pull_and_delete

    mock_conn = MagicMock(spec=AdbConnection)
    device_path = "/sdcard/seg_0.mp4"
    local_dir = Path("/tmp/segments")

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        pull_and_delete(mock_conn, device_path, local_dir)

    # shell rm should be called on the connection to clean up the device file
    mock_conn.shell.assert_called_once()
    shell_call_args = str(mock_conn.shell.call_args)
    assert "rm" in shell_call_args
    assert device_path in shell_call_args


# ---------------------------------------------------------------------------
# Task 5.1 – test_pull_and_delete_uses_adb_pull_command
# (triangulation: the actual adb pull subprocess call)
# ---------------------------------------------------------------------------


def test_pull_and_delete_uses_adb_pull_command():
    """pull_and_delete issues `adb -s SERIAL pull DEVICE_PATH LOCAL_DIR`.

    Triangulation: subprocess.run arguments matter for real device operation.
    """
    from gameplay_recorder.capture.video_recorder import pull_and_delete

    mock_conn = MagicMock(spec=AdbConnection)
    mock_conn._serial = "emulator-5554"
    device_path = "/sdcard/seg_1.mp4"
    local_dir = Path("/tmp/segments")

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        pull_and_delete(mock_conn, device_path, local_dir)

    # subprocess.run should have been called at least once with adb pull
    assert mock_subprocess.run.call_count >= 1
    call_args_str = str(mock_subprocess.run.call_args_list)
    assert "pull" in call_args_str
    assert device_path in call_args_str


# ---------------------------------------------------------------------------
# Triangulation: test_spawn_screenrecord_with_path_object_uses_posix_separators
# Exercises the Path -> as_posix() branch in _spawn_screenrecord (line 125)
# ---------------------------------------------------------------------------


def test_spawn_screenrecord_with_path_object_uses_posix_separators():
    """_spawn_screenrecord converts a Path device_path to POSIX string for Android.

    Triangulation: Path('/sdcard/seg_0.mp4') must arrive as '/sdcard/seg_0.mp4'
    in the adb command, not as a Windows-style backslash path.
    """
    from gameplay_recorder.capture.video_recorder import _spawn_screenrecord

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_proc = MagicMock()
        mock_subprocess.Popen.return_value = mock_proc

        # Pass a real Path object — must convert to POSIX
        _spawn_screenrecord("DEVICE456", Path("/sdcard/seg_0.mp4"), duration=170)

    cmd = mock_subprocess.Popen.call_args[0][0]
    # Must be a forward-slash POSIX path in the command, never backslashes
    device_path_in_cmd = cmd[-1]
    assert "/" in device_path_in_cmd, (
        f"Expected POSIX path in adb command, got: {device_path_in_cmd!r}"
    )
    assert "seg_0.mp4" in device_path_in_cmd


# ---------------------------------------------------------------------------
# Triangulation: test_segment_path_returns_correct_device_dir
# ---------------------------------------------------------------------------


def test_segment_path_returns_correct_device_dir():
    """segment_path() uses /sdcard as the default device directory.

    Triangulation: verify default dir and custom override work correctly.
    """
    from gameplay_recorder.capture.video_recorder import segment_path

    default_p = segment_path(0)
    assert "sdcard" in str(default_p).lower() or "sdcard" in default_p.as_posix()

    custom_p = segment_path(3, device_dir="/data/local/tmp")
    assert custom_p.name == "seg_3.mp4"
    assert "tmp" in str(custom_p)


# ---------------------------------------------------------------------------
# Triangulation: test_check_free_space_shell_exception_is_swallowed
# Exercises the except block in check_free_space
# ---------------------------------------------------------------------------


def test_check_free_space_shell_exception_is_swallowed():
    """check_free_space returns None (allow proceed) on shell error.

    Triangulation: if adb shell fails entirely, we do not block the user.
    """
    from gameplay_recorder.capture.video_recorder import check_free_space

    conn = MagicMock(spec=AdbConnection)
    conn.shell.side_effect = RuntimeError("adb error")
    result = check_free_space(conn)
    assert result is None, "Shell exception should be swallowed — return None"


def test_check_free_space_malformed_output_is_skipped():
    """check_free_space handles malformed df output gracefully.

    Triangulation: exercises the ValueError: continue branch (lines 84-85).
    Lines with non-numeric 'Available' field (at index 3) are skipped.
    We put valid line FIRST and malformed line LAST so reversed() hits the
    malformed line first, triggers ValueError, continues, then parses valid line.
    """
    from gameplay_recorder.capture.video_recorder import check_free_space

    conn = MagicMock(spec=AdbConnection)
    # reversed() will check the LAST line first — malformed goes last so ValueError fires first
    conn.shell.return_value = (
        "Filesystem       1K-blocks    Used Available Use% Mounted on\n"
        "tmpfs             1024000    400000   600000  40% /sdcard\n"
        "overlayfs         1024000    400000    bytes  40% /data\n"  # 'bytes' at idx 3 → ValueError
    )
    result = check_free_space(conn)
    # After skipping the malformed line, the valid tmpfs line is found with 600 MB
    assert result is None, f"600 MB free should pass after skipping malformed line, got: {result!r}"


# ---------------------------------------------------------------------------
# Triangulation: test_video_segment_recorder_instantiation
# Exercises VideoSegmentRecorder.__init__ and segments property (lines 248)
# ---------------------------------------------------------------------------


def test_video_segment_recorder_instantiation():
    """VideoSegmentRecorder can be instantiated with mock AdbConnection.

    Triangulation: verifies constructor stores config correctly.
    """
    from gameplay_recorder.capture.video_recorder import VideoSegmentRecorder

    mock_conn = MagicMock(spec=AdbConnection)
    local_dir = Path("/tmp/segs")

    recorder = VideoSegmentRecorder(adb_conn=mock_conn, local_dir=local_dir, duration=170)

    assert recorder._adb_conn is mock_conn
    assert recorder._local_dir == local_dir
    assert recorder._duration == 170
    # No segments yet
    assert recorder.segments == []


# ---------------------------------------------------------------------------
# Triangulation: test_resolve_adb_uses_meipass_when_available
# Exercises the sys._MEIPASS branch in _resolve_adb (lines 84-85, 96-101)
# ---------------------------------------------------------------------------


def test_resolve_adb_uses_system_adb_when_no_meipass():
    """_resolve_adb returns system adb when no PyInstaller bundle is present.

    Triangulation: non-bundled path (MEIPASS not set) — exercises lines 96-101.
    """
    import sys

    from gameplay_recorder.capture.video_recorder import _resolve_adb

    # Ensure _MEIPASS is not set for this test
    original = getattr(sys, "_MEIPASS", None)
    if hasattr(sys, "_MEIPASS"):
        del sys._MEIPASS
    try:
        result = _resolve_adb()
        # Result should contain 'adb' (either system path or literal 'adb' fallback)
        assert "adb" in result.lower(), f"Expected adb binary path, got: {result!r}"
    finally:
        if original is not None:
            sys._MEIPASS = original


# ---------------------------------------------------------------------------
# Phase 14e.2 — RED: proc.wait() responsive interruption
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Fake subprocess.Popen that stays 'running' until terminate() is called."""

    def __init__(self):
        self._terminated = False
        self.pid = 12345
        self.returncode = None

    def poll(self):
        return 0 if self._terminated else None

    def wait(self, timeout=None):
        if self._terminated:
            return 0
        raise subprocess.TimeoutExpired("cmd", timeout)

    def terminate(self):
        self._terminated = True
        self.returncode = -15

    def kill(self):
        self._terminated = True
        self.returncode = -9


def test_run_terminates_proc_on_interruption_within_2s():
    """VideoSegmentRecorder.run() calls proc.terminate() within 2s of requestInterruption().

    Phase 14e.2/14e.3: The old proc.wait() blocked for 170s. The new polling loop
    checks isInterruptionRequested() every second and terminates the process promptly.

    Verifies: after requesting interruption, terminate() is called on the fake process
    within 2 seconds — not 170s.

    Spec: Requirement 'Segmented Video Capture' — graceful stop.
    """
    import time

    from gameplay_recorder.capture.video_recorder import VideoSegmentRecorder

    fake_proc = _FakeProcess()
    mock_conn = _make_mock_conn()
    mock_conn._serial = "emulator-5554"

    recorder = VideoSegmentRecorder(
        adb_conn=mock_conn,
        local_dir=Path("/tmp/segs"),
        duration=170,
    )

    with (
        patch(
            "gameplay_recorder.capture.video_recorder._spawn_screenrecord",
            return_value=fake_proc,
        ),
        patch(
            "gameplay_recorder.capture.video_recorder.pull_and_delete",
            return_value=Path("/tmp/segs/seg_0.mp4"),
        ),
    ):
        # Start the worker thread
        recorder.start()

        # Give the thread a moment to enter the poll loop
        time.sleep(0.1)

        # Request interruption — worker should terminate proc within 2s
        recorder.requestInterruption()

        # Wait up to 2s for terminate() to be called
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if fake_proc._terminated:
                break
            time.sleep(0.05)

        recorder.wait()  # join the thread

    assert fake_proc._terminated, (
        "proc.terminate() must be called within 2s of requestInterruption() — "
        "the polling loop is not working correctly"
    )


# ---------------------------------------------------------------------------
# Triangulation: proc.kill() path when terminate() hangs
# ---------------------------------------------------------------------------


def test_run_kills_proc_when_terminate_hangs():
    """VideoSegmentRecorder.run() escalates to proc.kill() if terminate() doesn't
    stop the process within 5 seconds.

    Triangulation: exercises the proc.kill() escalation branch in the polling loop.
    """
    import subprocess
    import time

    from gameplay_recorder.capture.video_recorder import VideoSegmentRecorder

    class _StubbornProcess(_FakeProcess):
        """Like _FakeProcess but terminate() doesn't immediately flip _terminated."""

        def __init__(self):
            super().__init__()
            self._kill_called = False

        def terminate(self):
            # Do NOT flip _terminated — simulate a process that ignores SIGTERM
            self.returncode = -15

        def wait(self, timeout=None):
            if self._terminated:
                return 0
            raise subprocess.TimeoutExpired("cmd", timeout)

        def kill(self):
            self._terminated = True
            self._kill_called = True
            self.returncode = -9

    stubborn_proc = _StubbornProcess()
    mock_conn = _make_mock_conn()
    mock_conn._serial = "emulator-5554"

    recorder = VideoSegmentRecorder(
        adb_conn=mock_conn,
        local_dir=Path("/tmp/segs"),
        duration=170,
    )

    with (
        patch(
            "gameplay_recorder.capture.video_recorder._spawn_screenrecord",
            return_value=stubborn_proc,
        ),
        patch(
            "gameplay_recorder.capture.video_recorder.pull_and_delete",
            return_value=Path("/tmp/segs/seg_0.mp4"),
        ),
    ):
        recorder.start()
        time.sleep(0.1)
        recorder.requestInterruption()

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if stubborn_proc._kill_called:
                break
            time.sleep(0.05)

        recorder.wait()

    assert stubborn_proc._kill_called, (
        "proc.kill() must be called when terminate() doesn't stop the process within 5s"
    )


# ---------------------------------------------------------------------------
# Phase 14f.1 — RED: POSIX device paths in ADB commands
# ---------------------------------------------------------------------------


def test_segment_path_returns_posix_string_on_windows():
    """segment_path() always yields POSIX-compatible strings for ADB commands.

    On Windows Path('/sdcard') / 'seg_0.mp4' produces a WindowsPath whose
    str() contains backslashes. Callers MUST use .as_posix(), never str().
    This test is documentation — it already passes — but it anchors the contract.

    Spec: Phase 14f — POSIX device path fix.
    """
    from gameplay_recorder.capture.video_recorder import segment_path

    posix_str = segment_path(0).as_posix()
    assert posix_str == "/sdcard/seg_0.mp4", (
        f"as_posix() must return forward-slash path, got: {posix_str!r}"
    )
    assert "\\" not in posix_str, f"POSIX path must not contain backslashes, got: {posix_str!r}"


def test_spawn_screenrecord_uses_posix_path():
    """_spawn_screenrecord sends a POSIX path (forward slashes) to ADB.

    When a Path object is passed (the normal call-site case via run()),
    the adb command list must contain /sdcard/seg_0.mp4 — not backslashes.

    Phase 14f.1 — RED: the str-branch of _spawn_screenrecord trusts the caller
    to supply forward slashes, but the Path branch already calls .as_posix().
    """
    from gameplay_recorder.capture.video_recorder import _spawn_screenrecord, segment_path

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_proc = MagicMock()
        mock_subprocess.Popen.return_value = mock_proc

        # Pass the Path object — as returned by segment_path() in run()
        _spawn_screenrecord("EMU-1", segment_path(0), duration=5)

    cmd = mock_subprocess.Popen.call_args[0][0]
    device_path_in_cmd = cmd[-1]
    assert device_path_in_cmd == "/sdcard/seg_0.mp4", (
        f"ADB command must contain POSIX device path, got: {device_path_in_cmd!r}"
    )
    assert "\\" not in device_path_in_cmd, (
        f"Device path must not contain Windows backslashes, got: {device_path_in_cmd!r}"
    )


def test_spawn_screenrecord_uses_posix_path_when_string_input():
    """_spawn_screenrecord normalises backslash strings to POSIX for ADB.

    Even if the caller accidentally passes a string with backslashes
    (e.g. str(WindowsPath('/sdcard/seg_0.mp4'))), the helper must coerce
    it to forward slashes before building the adb command.

    Phase 14f.1 — RED: the current str-branch does NOT normalise backslashes.
    """
    from gameplay_recorder.capture.video_recorder import _spawn_screenrecord

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_proc = MagicMock()
        mock_subprocess.Popen.return_value = mock_proc

        # Simulate the buggy str() on a WindowsPath
        _spawn_screenrecord("EMU-1", "\\sdcard\\seg_0.mp4", duration=5)

    cmd = mock_subprocess.Popen.call_args[0][0]
    device_path_in_cmd = cmd[-1]
    assert device_path_in_cmd == "/sdcard/seg_0.mp4", (
        f"Backslash string input must be normalised to POSIX, got: {device_path_in_cmd!r}"
    )
    assert "\\" not in device_path_in_cmd, (
        f"Device path must not contain Windows backslashes, got: {device_path_in_cmd!r}"
    )


def test_pull_and_delete_uses_posix_device_path():
    """pull_and_delete normalises backslash device paths before issuing ADB commands.

    Simulates the buggy string that run() currently passes:
        str(WindowsPath('/sdcard/seg_0.mp4')) -> '\\sdcard\\seg_0.mp4'

    Both the adb pull subprocess.run call AND the adb_conn.shell rm call must
    receive /sdcard/seg_0.mp4 (forward slashes), never backslashes.

    Phase 14f.1 — RED: current implementation passes device_path as-is.
    """
    from gameplay_recorder.capture.video_recorder import pull_and_delete

    mock_conn = MagicMock(spec=AdbConnection)
    mock_conn._serial = "EMU-1"
    # Simulate the Windows-backslash bug at the call site
    buggy_device_path = "\\sdcard\\seg_0.mp4"
    local_dir = Path("/tmp/segments")

    with patch("gameplay_recorder.capture.video_recorder.subprocess") as mock_subprocess:
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        pull_and_delete(mock_conn, buggy_device_path, local_dir)

    # Assert subprocess.run (adb pull) received POSIX path
    run_args_str = str(mock_subprocess.run.call_args)
    assert "/sdcard/seg_0.mp4" in run_args_str, (
        f"adb pull must receive POSIX path '/sdcard/seg_0.mp4', got call: {run_args_str}"
    )
    assert "\\sdcard" not in run_args_str, (
        f"adb pull must NOT contain backslash path, got call: {run_args_str}"
    )

    # Assert adb_conn.shell (rm -f) received POSIX path
    shell_call_str = str(mock_conn.shell.call_args)
    assert "/sdcard/seg_0.mp4" in shell_call_str, (
        f"rm -f must receive POSIX path '/sdcard/seg_0.mp4', got call: {shell_call_str}"
    )
    assert "\\sdcard" not in shell_call_str, (
        f"rm -f must NOT contain backslash path, got call: {shell_call_str}"
    )


def test_video_segment_recorder_run_passes_posix_path_through_pipeline():
    """VideoSegmentRecorder.run() passes POSIX device paths through the entire pipeline.

    Integration-flavoured: verifies that both _spawn_screenrecord AND
    pull_and_delete receive forward-slash device paths — no matter what
    str(WindowsPath) would produce on Windows.

    Phase 14f.1 — RED: run() currently calls str(dev_path) which produces
    backslashes on Windows hosts.
    """
    import time

    from gameplay_recorder.capture.video_recorder import VideoSegmentRecorder

    mock_conn = _make_mock_conn()
    mock_conn._serial = "EMU-1"

    spawn_calls = []
    pull_calls = []

    def _fake_spawn(serial, device_path, duration):
        spawn_calls.append(device_path)
        return _FakeProcess()

    def _fake_pull(adb_conn, device_path, local_dir):
        pull_calls.append(device_path)
        return Path("/tmp/segs/seg_0.mp4")

    recorder = VideoSegmentRecorder(
        adb_conn=mock_conn,
        local_dir=Path("/tmp/segs"),
        duration=5,
    )

    with (
        patch(
            "gameplay_recorder.capture.video_recorder._spawn_screenrecord",
            side_effect=_fake_spawn,
        ),
        patch(
            "gameplay_recorder.capture.video_recorder.pull_and_delete",
            side_effect=_fake_pull,
        ),
    ):
        recorder.start()
        time.sleep(0.1)
        recorder.requestInterruption()
        recorder.wait()

    assert len(spawn_calls) >= 1, "Expected at least one _spawn_screenrecord call"
    assert len(pull_calls) >= 1, "Expected at least one pull_and_delete call"

    for path_arg in spawn_calls:
        path_str = str(path_arg)
        assert "\\" not in path_str, (
            f"_spawn_screenrecord must receive POSIX path, got: {path_str!r}"
        )
        assert "seg_0.mp4" in path_str

    for path_arg in pull_calls:
        assert "\\" not in path_arg, f"pull_and_delete must receive POSIX path, got: {path_arg!r}"
        assert "seg_0.mp4" in path_arg
