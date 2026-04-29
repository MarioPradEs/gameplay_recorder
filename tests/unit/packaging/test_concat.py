"""Tests for gameplay_recorder.packaging.concat.

Phase 8: Packaging / ZIP Assembler — concat step (Strict TDD).
Spec: Requirement "Segmented Video Capture".
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestConcatSingleSegment:
    """concat_segments with a single segment does NOT call ffmpeg."""

    def test_concat_single_segment_no_ffmpeg(self, tmp_path: Path) -> None:
        """One segment: concat_segments returns that path without calling ffmpeg.

        Spec: Requirement "Segmented Video Capture", Scenario "Short session < 170s".
        """
        from gameplay_recorder.packaging.concat import concat_segments

        seg = tmp_path / "seg_0.mp4"
        seg.write_bytes(b"fake-video")

        output = tmp_path / "gameplay.mp4"
        with patch("subprocess.run") as mock_run:
            result = concat_segments([seg], output)
            mock_run.assert_not_called()

        # Returns the single segment path (or a copy at output) — not ffmpeg output
        assert result.exists()

    def test_concat_single_segment_returns_path_with_output_name(self, tmp_path: Path) -> None:
        """One segment: the returned path is the output path."""
        from gameplay_recorder.packaging.concat import concat_segments

        seg = tmp_path / "seg_0.mp4"
        seg.write_bytes(b"fake-video")

        output = tmp_path / "gameplay.mp4"
        with patch("subprocess.run"):
            result = concat_segments([seg], output)

        assert result == output


class TestConcatMultiSegment:
    """concat_segments with multiple segments calls ffmpeg concat."""

    def test_concat_multi_segment_calls_ffmpeg(self, tmp_path: Path) -> None:
        """Two+ segments: ffmpeg called with -f concat -safe 0 -c copy.

        Spec: Requirement "Segmented Video Capture", Scenario "Multi-segment concat".
        """
        from gameplay_recorder.packaging.concat import concat_segments

        seg0 = tmp_path / "seg_0.mp4"
        seg1 = tmp_path / "seg_1.mp4"
        seg0.write_bytes(b"fake0")
        seg1.write_bytes(b"fake1")

        output = tmp_path / "gameplay.mp4"

        # Fake ffmpeg creating the output
        def fake_run(cmd, *args, **kwargs):
            output.write_bytes(b"concat-result")
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("gameplay_recorder.packaging.concat._resolve_ffmpeg", return_value="ffmpeg"):
            with patch("subprocess.run", side_effect=fake_run) as mock_run:
                concat_segments([seg0, seg1], output)

        # ffmpeg was called
        assert mock_run.called
        call_args = mock_run.call_args[0][0]  # list of cmd tokens
        assert "-f" in call_args
        assert "concat" in call_args
        assert "-safe" in call_args
        assert "0" in call_args
        assert "-c" in call_args
        assert "copy" in call_args

    def test_concat_multi_segment_output_is_target(self, tmp_path: Path) -> None:
        """concat_segments returns the output path when ffmpeg succeeds."""
        from gameplay_recorder.packaging.concat import concat_segments

        seg0 = tmp_path / "seg_0.mp4"
        seg1 = tmp_path / "seg_1.mp4"
        seg0.write_bytes(b"fake0")
        seg1.write_bytes(b"fake1")

        output = tmp_path / "gameplay.mp4"

        def fake_run(cmd, *args, **kwargs):
            output.write_bytes(b"merged")
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("gameplay_recorder.packaging.concat._resolve_ffmpeg", return_value="ffmpeg"):
            with patch("subprocess.run", side_effect=fake_run):
                result = concat_segments([seg0, seg1], output)

        assert result == output

    def test_concat_file_list_contains_all_segments(self, tmp_path: Path) -> None:
        """The temp concat-list file written by concat_segments references all segment paths.

        Spec: Requirement "Segmented Video Capture", Scenario "Multi-segment concat".
        """
        from gameplay_recorder.packaging.concat import concat_segments

        seg0 = tmp_path / "seg_0.mp4"
        seg1 = tmp_path / "seg_1.mp4"
        seg2 = tmp_path / "seg_2.mp4"
        for seg in (seg0, seg1, seg2):
            seg.write_bytes(b"fake")

        output = tmp_path / "gameplay.mp4"
        captured_list_content: list[str] = []

        def fake_run(cmd, *args, **kwargs):
            # The concat list file path is passed to ffmpeg as -i <path>
            # Find -i in cmd and read the file
            for i, tok in enumerate(cmd):
                if tok == "-i" and i + 1 < len(cmd):
                    list_file = Path(cmd[i + 1])
                    if list_file.exists():
                        captured_list_content.append(list_file.read_text(encoding="utf-8"))
            output.write_bytes(b"merged")
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("gameplay_recorder.packaging.concat._resolve_ffmpeg", return_value="ffmpeg"):
            with patch("subprocess.run", side_effect=fake_run):
                concat_segments([seg0, seg1, seg2], output)

        assert len(captured_list_content) == 1
        list_text = captured_list_content[0]
        # Each segment path must appear in the concat list
        for seg in (seg0, seg1, seg2):
            assert seg.name in list_text or str(seg) in list_text


class TestConcatEdgeCases:
    """Edge cases for concat_segments."""

    def test_concat_raises_on_empty_segments(self, tmp_path: Path) -> None:
        """concat_segments with empty list raises ValueError."""
        from gameplay_recorder.packaging.concat import concat_segments

        output = tmp_path / "out.mp4"
        with pytest.raises(ValueError, match="segments"):
            concat_segments([], output)

    def test_concat_single_segment_copies_to_output(self, tmp_path: Path) -> None:
        """When 1 segment, output file is the segment content (copy or rename)."""
        from gameplay_recorder.packaging.concat import concat_segments

        seg = tmp_path / "seg_0.mp4"
        seg.write_bytes(b"the-real-video-data")
        output = tmp_path / "gameplay.mp4"

        with patch("subprocess.run"):
            result = concat_segments([seg], output)

        assert result.read_bytes() == b"the-real-video-data"
