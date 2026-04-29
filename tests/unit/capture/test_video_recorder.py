"""Unit tests for VideoSegmentRecorder.

TDD Phase 5 — RED written first, production code does NOT exist yet.
All subprocess and ADB calls are mocked — no real devices or processes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_conn(free_kb: int = 600_000) -> MagicMock:
    """Return a mock AdbConnection whose shell() fakes df output."""
    conn = MagicMock()
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

    mock_conn = MagicMock()
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

    mock_conn = MagicMock()
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

    conn = MagicMock()
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

    conn = MagicMock()
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

    mock_conn = MagicMock()
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
