"""RED phase — Phase 12.1 + 14b.1: UI Widget tests.

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
  - Phase 14b.1: UX labels, version field, device status label, tooltips
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from gameplay_recorder.ui.done_screen import DoneScreen
from gameplay_recorder.ui.idle_screen import IdleScreen
from gameplay_recorder.ui.recording_screen import RecordingScreen

# ---------------------------------------------------------------------------
# IdleScreen — game dropdown
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_idle_screen_has_game_dropdown(qtbot):
    """IdleScreen exposes a QComboBox with 'Zombie Gore' as display text and 'zombie_gore' as data.

    Spec: Requirement "GUI State Machine" — IDLE state UI has a game dropdown.
    Phase 14b: display text is human-readable; internal data (game_id) stays snake_case.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    assert screen.game_dropdown is not None
    # Display text must be human-readable
    items_text = [screen.game_dropdown.itemText(i) for i in range(screen.game_dropdown.count())]
    assert "Zombie Gore" in items_text
    # Internal data (game_id sent to session_meta.json) must remain snake_case
    items_data = [screen.game_dropdown.itemData(i) for i in range(screen.game_dropdown.count())]
    assert "zombie_gore" in items_data


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
    """Record button is enabled when device serial AND all required form fields are set.

    Spec: Requirement "ADB Device Discovery", Scenario "Single device connected" —
    Record button MAY be enabled when exactly one authorized device is found AND
    version + player fields are filled (Phase 14c: form validation).
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("emulator-5554")  # valid device serial
    screen.version_field.setText("1.0.0")
    screen.player_name_field.setText("tester")

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


# ---------------------------------------------------------------------------
# Phase 14b.1 RED — IdleScreen UX: labels, version field, device status, tooltips
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_game_dropdown_displays_zombie_gore_with_capitalization(qtbot):
    """game_dropdown shows 'Zombie Gore' as display text but stores 'zombie_gore' as data.

    Spec: Phase 14b — dropdown display map; game_id in session_meta.json uses snake_case.
    currentText() == "Zombie Gore" (user-visible), currentData() == "zombie_gore" (game_id).
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    assert screen.game_dropdown.currentText() == "Zombie Gore"
    assert screen.game_dropdown.currentData() == "zombie_gore"


@pytest.mark.gui
def test_idle_screen_has_game_label(qtbot):
    """IdleScreen has a QLabel with text 'Game' or 'Game:' visible next to the dropdown.

    Spec: Phase 14b — labels-on-left UX requirement from user feedback.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    labels = [lbl.text() for lbl in screen.findChildren(QLabel)]
    assert any(text in ("Game", "Game:") for text in labels)


@pytest.mark.gui
def test_idle_screen_has_version_label_and_field(qtbot):
    """IdleScreen has a version_field QLineEdit and a 'Version'/'Version:' label.

    Spec: Requirement 'GUI State Machine' — IDLE state requires version field.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    from PySide6.QtWidgets import QLineEdit

    assert hasattr(screen, "version_field")
    assert isinstance(screen.version_field, QLineEdit)

    labels = [lbl.text() for lbl in screen.findChildren(QLabel)]
    assert any(text in ("Version", "Version:") for text in labels)


@pytest.mark.gui
def test_idle_screen_has_player_label(qtbot):
    """IdleScreen has a QLabel with text 'Player' or 'Player:' next to the name field.

    Spec: Phase 14b — labels-on-left UX requirement.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    labels = [lbl.text() for lbl in screen.findChildren(QLabel)]
    assert any(text in ("Player", "Player:") for text in labels)


@pytest.mark.gui
def test_idle_screen_has_device_status_label(qtbot):
    """IdleScreen has a device_status_label QLabel; default text contains 'No device'.

    Spec: Requirement 'GUI State Machine' — IDLE state requires device status display.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    assert hasattr(screen, "device_status_label")
    assert isinstance(screen.device_status_label, QLabel)
    assert "no device" in screen.device_status_label.text().lower()


@pytest.mark.gui
def test_set_device_status_updates_label(qtbot):
    """set_device_status('ABC123') sets label text to contain 'ABC123'.

    When all required fields are also set, enables the Record button.
    Spec: Phase 14b — device status label reflects serial; Record enabled when
    device + version + player are all present (Phase 14c: form validation).
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("ABC123")

    assert "ABC123" in screen.device_status_label.text()
    # Button is still disabled because version/player are empty
    assert not screen.record_button.isEnabled()

    # Fill all required fields → button enabled
    screen.version_field.setText("1.0.0")
    screen.player_name_field.setText("tester")
    assert screen.record_button.isEnabled()


@pytest.mark.gui
def test_set_device_status_none_disables_button_and_resets_label(qtbot):
    """set_device_status(None) disables Record button and resets label to 'No device'.

    Spec: Phase 14b — when no device, label shows 'No device' and Record stays disabled.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    # First enable, then reset
    screen.set_device_status("ABC123")
    screen.set_device_status(None)

    assert "no device" in screen.device_status_label.text().lower()
    assert not screen.record_button.isEnabled()


@pytest.mark.gui
def test_game_dropdown_has_tooltip(qtbot):
    """game_dropdown has a non-empty tooltip.

    Spec: Phase 14b — UX request for explanatory tooltips on form fields.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    assert screen.game_dropdown.toolTip() != ""


@pytest.mark.gui
def test_version_field_has_tooltip(qtbot):
    """version_field has a non-empty tooltip.

    Spec: Phase 14b — UX request for explanatory tooltips.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    assert screen.version_field.toolTip() != ""


@pytest.mark.gui
def test_player_name_field_has_tooltip(qtbot):
    """player_name_field has a non-empty tooltip.

    Spec: Phase 14b — UX request for explanatory tooltips.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    assert screen.player_name_field.toolTip() != ""


# ---------------------------------------------------------------------------
# Phase 6.3 RED — RecordingScreen must not have segment counter post-pivot
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_recording_screen_no_longer_has_segment_label(qtbot):
    """After scrcpy pivot, RecordingScreen must not have a segment counter widget."""
    from gameplay_recorder.ui.recording_screen import RecordingScreen

    screen = RecordingScreen()
    qtbot.addWidget(screen)
    # Pre-pivot RecordingScreen had `_segment_label` (counted MP4 segments).
    # Post-pivot it must not exist (single-file recording, no segments).
    assert not hasattr(screen, "_segment_label"), (
        "RecordingScreen._segment_label must be removed in Phase 6"
    )
