"""Unit tests for the _validate_mp4 helper.

TDD Phase 2 (RED) — written BEFORE production code exists.
Tests cover moov atom detection in various file configurations.

Spec: gameplay-recorder-shutdown-and-touch-fixes / Phase 2: mp4 validation
"""

from __future__ import annotations

from pathlib import Path

from gameplay_recorder.capture.scrcpy_recorder import _validate_mp4


# ---------------------------------------------------------------------------
# Phase 2.1 — _validate_mp4 helper tests
# ---------------------------------------------------------------------------


def test_validate_mp4_returns_true_when_moov_in_first_128kb(tmp_path):
    """_validate_mp4() returns (True, None) when moov atom is in the first 128 KB.

    Spec: moov in early region → file is playable.
    """
    f = tmp_path / "ok.mp4"
    # ftyp + early moov atom (within 128 KB)
    f.write_bytes(b"\x00\x00\x00\x20" + b"ftypisom" + b"\x00" * 100 + b"moov" + b"\x00" * 1000)
    ok, reason = _validate_mp4(f)
    assert ok is True
    assert reason is None


def test_validate_mp4_returns_true_when_moov_in_last_128kb(tmp_path):
    """_validate_mp4() returns (True, None) when moov atom is in the last 128 KB.

    Spec: moov at end (large file, normal mp4 structure) → file is playable.
    """
    f = tmp_path / "ok_late.mp4"
    # ftyp at start, mdat in middle (large), moov at very end
    f.write_bytes(
        b"\x00\x00\x00\x20"
        + b"ftypisom"
        + b"\x00" * (300 * 1024)  # 300 KB of mdat-ish padding
        + b"moov"
        + b"\x00" * 1000
    )
    ok, reason = _validate_mp4(f)
    assert ok is True
    assert reason is None


def test_validate_mp4_returns_false_when_no_moov(tmp_path):
    """_validate_mp4() returns (False, reason) when no moov atom is found.

    Spec: missing moov → file is likely unplayable. Reason must mention 'moov'.
    """
    f = tmp_path / "bad.mp4"
    # ftyp + mdat only, no moov anywhere
    f.write_bytes(
        b"\x00\x00\x00\x20"
        + b"ftypisom"
        + b"\x00" * 100
        + b"free"
        + b"\x00" * 100
        + b"mdat"
        + b"\x00" * (300 * 1024)
    )
    ok, reason = _validate_mp4(f)
    assert ok is False
    assert reason is not None
    assert "moov" in reason.lower()


def test_validate_mp4_returns_false_when_file_missing(tmp_path):
    """_validate_mp4() returns (False, reason) when file does not exist.

    Spec: missing file edge case → reason must mention 'missing'.
    """
    f = tmp_path / "nope.mp4"
    ok, reason = _validate_mp4(f)
    assert ok is False
    assert reason is not None
    assert "missing" in reason.lower()


def test_validate_mp4_returns_false_when_file_empty(tmp_path):
    """_validate_mp4() returns (False, reason) when file is 0 bytes.

    Spec: empty file edge case → reason must mention 'empty'.
    """
    f = tmp_path / "empty.mp4"
    f.write_bytes(b"")
    ok, reason = _validate_mp4(f)
    assert ok is False
    assert reason is not None
    assert "empty" in reason.lower()


def test_validate_mp4_handles_small_file_under_128kb(tmp_path):
    """_validate_mp4() correctly scans files smaller than 128 KB.

    Spec: small file should be scanned as a single region, not two.
    Should still detect moov atom correctly.
    """
    # File smaller than 128KB region — should still work, scan whole file once
    f = tmp_path / "small_ok.mp4"
    f.write_bytes(b"ftypisom" + b"\x00" * 50 + b"moov" + b"\x00" * 50)
    ok, reason = _validate_mp4(f)
    assert ok is True
    assert reason is None
