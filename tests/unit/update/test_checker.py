"""Tests for gameplay_recorder.update.checker.

Phase 10: Update / Checker — Strict TDD (RED first).
Spec: Requirement "Auto-Update Check".
Design: update/checker.py — compare_semver, check_for_update.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


class TestNewerVersionAvailable:
    """Spec: Requirement "Auto-Update Check", Scenario "Newer version available"."""

    def test_newer_version_emits_update_available(self) -> None:
        """check_for_update returns the newer version string when one is available.

        Given app version 0.1.0 and GitHub Releases returning v0.2.0,
        the function must return "0.2.0" (latest_version, is_newer == True).
        Spec: Requirement "Auto-Update Check", Scenario "Newer version available".
        """
        from gameplay_recorder.update.checker import check_for_update

        payload = json.dumps({"tag_name": "v0.2.0"}).encode()
        mock_response = MagicMock(spec=["read", "__enter__", "__exit__"])
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = payload

        with patch("gameplay_recorder.update.checker.urlopen", return_value=mock_response):
            latest_version = check_for_update("0.1.0")

        is_newer = latest_version is not None
        assert latest_version == "0.2.0"
        assert is_newer is True


class TestSameVersionNoUpdate:
    """Spec: Requirement "Auto-Update Check", Scenario "No newer version"."""

    def test_same_version_no_update(self) -> None:
        """check_for_update returns None when the remote version equals current.

        Given app version 0.1.0 and GitHub Releases returning v0.1.0,
        the function must return None (is_newer == False).
        Spec: Requirement "Auto-Update Check", Scenario "No newer version".
        """
        from gameplay_recorder.update.checker import check_for_update

        payload = json.dumps({"tag_name": "v0.1.0"}).encode()
        mock_response = MagicMock(spec=["read", "__enter__", "__exit__"])
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = payload

        with patch("gameplay_recorder.update.checker.urlopen", return_value=mock_response):
            result = check_for_update("0.1.0")

        assert result is None


class TestNetworkErrorSuppressed:
    """Spec: Requirement "Auto-Update Check", Scenario "Network unavailable"."""

    def test_network_error_suppressed(self) -> None:
        """check_for_update returns None silently when urlopen raises OSError.

        Given the host has no internet connection (OSError from urlopen),
        the function must return None without raising any exception.
        Spec: Requirement "Auto-Update Check", Scenario "Network unavailable".
        Design: checker.py swallows all exceptions (non-blocking banner requirement).
        """
        from gameplay_recorder.update.checker import check_for_update

        with patch(
            "gameplay_recorder.update.checker.urlopen", side_effect=OSError("Network error")
        ):
            result = check_for_update("0.1.0")

        assert result is None


class TestMalformedJsonSuppressed:
    """Spec: Requirement "Auto-Update Check" — malformed response handling."""

    def test_malformed_json_suppressed(self) -> None:
        """check_for_update returns None silently when the response is invalid JSON.

        Given the GitHub endpoint returns non-JSON content (e.g. HTML error page),
        the function must return None without raising any exception.
        Design: checker.py swallows all exceptions.
        """
        from gameplay_recorder.update.checker import check_for_update

        mock_response = MagicMock(spec=["read", "__enter__", "__exit__"])
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b"<html>Not JSON</html>"

        with patch("gameplay_recorder.update.checker.urlopen", return_value=mock_response):
            result = check_for_update("0.1.0")

        assert result is None


class TestSemverCompare:
    """Direct unit tests for compare_semver(a, b) -> int.

    Design: compare_semver returns -1 if a < b, 0 if a == b, 1 if a > b.
    """

    def test_semver_compare_equal_versions(self) -> None:
        """compare_semver returns 0 when both versions are identical.

        Task 10.1, test 5 — semver compare logic: equal case.
        """
        from gameplay_recorder.update.checker import compare_semver

        assert compare_semver("0.1.0", "0.1.0") == 0

    def test_semver_compare_patch_bump_a_greater(self) -> None:
        """compare_semver returns 1 when a is a patch bump above b.

        Task 10.1, test 5 — semver compare logic: 0.1.1 > 0.1.0.
        """
        from gameplay_recorder.update.checker import compare_semver

        assert compare_semver("0.1.1", "0.1.0") == 1

    def test_semver_compare_minor_bump_a_greater(self) -> None:
        """compare_semver returns 1 when a has a higher minor than b.

        Task 10.1, test 5 — semver compare logic: 0.2.0 > 0.1.9.
        Multi-digit component: ensures numeric (not lexicographic) comparison.
        """
        from gameplay_recorder.update.checker import compare_semver

        assert compare_semver("0.2.0", "0.1.9") == 1

    def test_semver_compare_a_less_than_b(self) -> None:
        """compare_semver returns -1 when a is older than b.

        Task 10.1, test 5 — semver compare logic: a < b case.
        """
        from gameplay_recorder.update.checker import compare_semver

        assert compare_semver("0.1.0", "0.2.0") == -1

    def test_semver_compare_multi_digit_components(self) -> None:
        """compare_semver handles multi-digit version components correctly.

        "1.10.0" must be greater than "1.9.9" (numeric, not lexicographic).
        Task 10.1, test 5 — multi-digit component coverage.
        """
        from gameplay_recorder.update.checker import compare_semver

        assert compare_semver("1.10.0", "1.9.9") == 1
        assert compare_semver("1.9.9", "1.10.0") == -1

    def test_semver_compare_major_bump(self) -> None:
        """compare_semver handles a major version bump correctly.

        "2.0.0" must be greater than "1.9.9" (major component dominates).
        Triangulation: ensures the first component is also compared numerically.
        """
        from gameplay_recorder.update.checker import compare_semver

        assert compare_semver("2.0.0", "1.9.9") == 1
        assert compare_semver("1.9.9", "2.0.0") == -1
