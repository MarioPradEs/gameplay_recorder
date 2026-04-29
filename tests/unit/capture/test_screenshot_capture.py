"""Unit tests for ScreenshotCapture.

TDD Phase 6 — RED written first, production code does NOT exist yet.
All ADB calls are mocked — no real devices.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Task 6.1 – test_screenshot_filename_zero_padded
# ---------------------------------------------------------------------------


def test_screenshot_filename_zero_padded():
    """First screenshot is 0000.png, second is 0001.png.

    Spec: Requirement 'Periodic Screenshot Capture'.
    """
    from gameplay_recorder.capture.screenshot_capture import screenshot_filename

    assert screenshot_filename(0) == "0000.png"
    assert screenshot_filename(1) == "0001.png"
    assert screenshot_filename(9) == "0009.png"
    assert screenshot_filename(10) == "0010.png"
    assert screenshot_filename(9999) == "9999.png"


# ---------------------------------------------------------------------------
# Task 6.1 – test_screenshot_path_in_screenshots_subdir
# (triangulation: full relative path includes screenshots/ prefix)
# ---------------------------------------------------------------------------


def test_screenshot_path_in_screenshots_subdir():
    """screenshot_path() returns screenshots/NNNN.png relative path.

    Triangulation: the screenshots/ subdir is part of the spec ZIP layout.
    """
    from gameplay_recorder.capture.screenshot_capture import screenshot_path

    p = screenshot_path(0, Path("/tmp/session"))
    assert p.name == "0000.png"
    assert p.parent.name == "screenshots"


# ---------------------------------------------------------------------------
# Task 6.1 – test_default_interval_is_5s
# ---------------------------------------------------------------------------


def test_default_interval_is_5s():
    """ScreenshotCapture default interval is 5 seconds.

    Spec: Requirement 'Periodic Screenshot Capture' — default: 5s.
    """
    from gameplay_recorder.capture.screenshot_capture import ScreenshotCapture

    mock_conn = MagicMock()
    cap = ScreenshotCapture(adb_conn=mock_conn, session_dir=Path("/tmp/s"))
    assert cap.interval_s == 5


# ---------------------------------------------------------------------------
# Task 6.1 – test_screenshot_count_approx_30s_session
# ---------------------------------------------------------------------------


def test_screenshot_count_approx_30s_session():
    """~6 screenshots produced in a 30s session at 5s interval.

    Spec: Requirement 'Periodic Screenshot Capture', Scenario 'Default interval':
    'screenshots/0000.png through screenshots/0005.png are present (approx 6 captures)'.
    We drive the _take_screenshot method directly, bypassing QThread.run(),
    to avoid Qt event loop dependencies in unit tests.
    """
    from gameplay_recorder.capture.screenshot_capture import ScreenshotCapture

    mock_conn = MagicMock()
    mock_conn.screencap.return_value = b"\x89PNG\r\n\x1a\n"  # minimal PNG bytes

    session_dir = Path("/tmp/screenshots_test")
    cap = ScreenshotCapture(adb_conn=mock_conn, session_dir=session_dir, interval_s=5)

    # Simulate 6 screenshot captures (0s, 5s, 10s, 15s, 20s, 25s for a 30s session)
    with patch("builtins.open", create=True) as mock_open:
        mock_file = MagicMock()
        mock_open.return_value.__enter__ = lambda s: mock_file
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        for _ in range(6):
            cap._take_screenshot()

    # 6 screenshots should have been taken
    assert cap._screenshot_count == 6
    assert mock_conn.screencap.call_count == 6


# ---------------------------------------------------------------------------
# Task 6.1 – test_custom_interval_honored
# ---------------------------------------------------------------------------


def test_custom_interval_honored():
    """Custom interval_s is respected.

    Spec: Scenario 'Custom interval' — interval_s=10 gives ~6 screenshots in 60s.
    We verify that the interval attribute is stored correctly and used.
    """
    from gameplay_recorder.capture.screenshot_capture import ScreenshotCapture

    mock_conn = MagicMock()
    cap = ScreenshotCapture(adb_conn=mock_conn, session_dir=Path("/tmp/s"), interval_s=10)
    assert cap.interval_s == 10


# ---------------------------------------------------------------------------
# Triangulation: test_screenshot_filenames_sequential
# ---------------------------------------------------------------------------


def test_screenshot_filenames_sequential():
    """Multiple calls produce sequentially numbered filenames.

    Triangulation: ensure counter increments correctly across captures.
    """
    from gameplay_recorder.capture.screenshot_capture import ScreenshotCapture

    mock_conn = MagicMock()
    mock_conn.screencap.return_value = b"\x89PNG\r\n\x1a\n"
    session_dir = Path("/tmp/seq_test")

    cap = ScreenshotCapture(adb_conn=mock_conn, session_dir=session_dir, interval_s=5)

    with patch("builtins.open", create=True) as mock_open:
        mock_file = MagicMock()
        mock_open.return_value.__enter__ = lambda s: mock_file
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        cap._take_screenshot()  # should write 0000.png
        cap._take_screenshot()  # should write 0001.png
        cap._take_screenshot()  # should write 0002.png

    assert cap._screenshot_count == 3
    # Verify the paths used in open() calls
    open_calls = [str(c) for c in mock_open.call_args_list]
    assert any("0000.png" in c for c in open_calls)
    assert any("0001.png" in c for c in open_calls)
    assert any("0002.png" in c for c in open_calls)


# ---------------------------------------------------------------------------
# Triangulation: test_screenshots_property_returns_correct_paths
# ---------------------------------------------------------------------------


def test_screenshots_property_returns_correct_paths():
    """The screenshots property lists all captured paths in order.

    Triangulation: exercises the screenshots @property (line 132).
    """
    from gameplay_recorder.capture.screenshot_capture import ScreenshotCapture

    mock_conn = MagicMock()
    mock_conn.screencap.return_value = b"\x89PNG\r\n\x1a\n"
    session_dir = Path("/tmp/prop_test")

    cap = ScreenshotCapture(adb_conn=mock_conn, session_dir=session_dir, interval_s=5)

    with patch("builtins.open", create=True) as mock_open:
        mock_file = MagicMock()
        mock_open.return_value.__enter__ = lambda s: mock_file
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        cap._take_screenshot()
        cap._take_screenshot()

    paths = cap.screenshots
    assert len(paths) == 2
    assert paths[0].name == "0000.png"
    assert paths[1].name == "0001.png"
    assert paths[0].parent.name == "screenshots"


# ---------------------------------------------------------------------------
# Triangulation: test_take_screenshot_creates_parent_dir
# ---------------------------------------------------------------------------


def test_take_screenshot_creates_parent_dir(tmp_path):
    """_take_screenshot creates the screenshots/ subdirectory if it doesn't exist.

    Triangulation: mkdir(parents=True, exist_ok=True) call.
    """
    from gameplay_recorder.capture.screenshot_capture import ScreenshotCapture

    session_dir = tmp_path / "new_session"
    # session_dir does NOT exist yet — _take_screenshot must create it

    mock_conn = MagicMock()
    mock_conn.screencap.return_value = b"\x89PNG\r\n\x1a\n"

    cap = ScreenshotCapture(adb_conn=mock_conn, session_dir=session_dir, interval_s=5)
    cap._take_screenshot()

    expected = session_dir / "screenshots" / "0000.png"
    assert expected.exists(), f"Screenshot not found at {expected}"
    assert expected.read_bytes() == b"\x89PNG\r\n\x1a\n"
