"""RED phase — Phase 12.1: UI Widget tests.

Tests the individual screen widgets and the update banner.
Widgets live in separate modules per design:
  - gameplay_recorder.ui.idle_screen    → IdleScreen
  - gameplay_recorder.ui.recording_screen → RecordingScreen
  - gameplay_recorder.ui.done_screen    → DoneScreen

Spec references:
  - Requirement "ADB Device Discovery": device status, Record button enabled/disabled
  - Requirement "GUI State Machine": IDLE/RECORDING/DONE UI contracts
  - Requirement "ZIP Packaging", Scenario "Valid ZIP produced": DoneScreen ZIP path
  - Requirement "Auto-Update Check": update banner visibility
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gameplay_recorder.ui.done_screen import DoneScreen
from gameplay_recorder.ui.idle_screen import IdleScreen
from gameplay_recorder.ui.recording_screen import RecordingScreen

# ---------------------------------------------------------------------------
# IdleScreen — game dropdown
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_idle_screen_has_game_dropdown(qtbot):
    """IdleScreen exposes a QComboBox with 'zombie_gore' as an entry.

    Spec: Requirement "GUI State Machine" — IDLE state UI has a game dropdown.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    assert screen.game_dropdown is not None
    items = [screen.game_dropdown.itemText(i) for i in range(screen.game_dropdown.count())]
    assert "zombie_gore" in items


# ---------------------------------------------------------------------------
# IdleScreen — Record button device-status gating
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_idle_screen_record_button_disabled_without_device(qtbot):
    """Record button is disabled when device_status is an error string.

    Spec: Requirement "ADB Device Discovery", Scenario "No device connected" —
    Record button MUST be disabled when no device is available.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status(None)  # None = no device / error state

    assert not screen.record_button.isEnabled()


@pytest.mark.gui
def test_idle_screen_record_button_enabled_with_device(qtbot):
    """Record button is enabled when a valid device serial is provided.

    Spec: Requirement "ADB Device Discovery", Scenario "Single device connected" —
    Record button MAY be enabled when exactly one authorized device is found.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("emulator-5554")  # valid device serial

    assert screen.record_button.isEnabled()


# ---------------------------------------------------------------------------
# RecordingScreen — elapsed timer label
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_recording_screen_shows_timer(qtbot):
    """RecordingScreen.update_elapsed(5) updates the timer label to '0:05'.

    Spec: Requirement "GUI State Machine" — RECORDING state UI has elapsed timer.
    """
    screen = RecordingScreen()
    qtbot.addWidget(screen)

    screen.update_elapsed(5)

    assert screen.timer_label.text() == "0:05"


# ---------------------------------------------------------------------------
# DoneScreen — ZIP path display
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_done_screen_shows_zip_path(qtbot):
    """DoneScreen.set_zip_path(path) displays the filename in a label.

    Spec: Requirement "ZIP Packaging", Scenario "Valid ZIP produced" —
    done screen must show the path to the produced ZIP.
    """
    screen = DoneScreen()
    qtbot.addWidget(screen)

    screen.set_zip_path(Path("/tmp/foo.zip"))

    assert "foo.zip" in screen.zip_path_label.text()


# ---------------------------------------------------------------------------
# Update banner — visibility
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_update_banner_shown_when_update_available(qtbot):
    """IdleScreen shows the update banner when set_update_available('0.2.0') is called.

    Spec: Requirement "Auto-Update Check", Scenario "Newer version available" —
    a non-blocking banner must appear with the new version string.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_update_available("0.2.0")

    assert screen.update_banner.isVisible()
    assert "0.2.0" in screen.update_banner.text()


@pytest.mark.gui
def test_update_banner_hidden_when_no_update(qtbot):
    """IdleScreen hides the update banner when set_update_available(None) is called.

    Spec: Requirement "Auto-Update Check", Scenario "No newer version" —
    no banner must be shown when running the latest version.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    # Ensure banner starts hidden (or explicitly hide it)
    screen.set_update_available(None)

    assert not screen.update_banner.isVisible()
