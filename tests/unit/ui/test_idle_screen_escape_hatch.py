"""RED tests for IdleScreen escape-hatch UX (Phase 4.1).

When detect_touch_device() returns None, the UI must:
  - Disable the Record button by default.
  - Show a visible warning message.
  - Show a "Continue anyway" checkbox.
  - When checkbox is checked: re-enable Record.
  - Expose escape_hatch_active property.

Spec: Phase 4 — escape-hatch UX, gameplay-recorder-shutdown-and-touch-fixes.
"""

from __future__ import annotations

import pytest

from gameplay_recorder.ui.idle_screen import IdleScreen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fill_form(screen: IdleScreen) -> None:
    """Fill version and player fields so form validity is not the bottleneck."""
    screen.version_field.setText("1.0.0")
    screen.player_name_field.setText("tester")


# ---------------------------------------------------------------------------
# Record button state based on touch device presence
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_record_button_enabled_when_touch_device_detected(qtbot):
    """When touch_device is a valid string, Record button is enabled (with form filled).

    Spec: escape-hatch UX — normal flow, device present → Record enabled.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("emulator-5554")
    _fill_form(screen)
    screen.set_touch_device("/dev/input/event8")

    assert screen.record_button.isEnabled()


@pytest.mark.gui
def test_record_button_disabled_when_no_touch_device(qtbot):
    """When touch_device is None, Record button is disabled by default.

    Spec: escape-hatch UX — no touch device → Record disabled until escape-hatch checked.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("emulator-5554")
    _fill_form(screen)
    screen.set_touch_device(None)

    assert not screen.record_button.isEnabled()


# ---------------------------------------------------------------------------
# Escape-hatch widgets visible only when touch_device is None
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_escape_hatch_checkbox_visible_when_no_touch_device(qtbot):
    """When touch_device is None, the escape-hatch checkbox is visible.

    Spec: escape-hatch UX — checkbox shown when no touch device detected.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device(None)

    assert screen.escape_hatch_checkbox.isVisible()


@pytest.mark.gui
def test_escape_hatch_warning_label_visible_when_no_touch_device(qtbot):
    """When touch_device is None, the warning label is visible.

    Spec: escape-hatch UX — warning message shown when no touch device detected.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device(None)

    assert screen.no_touch_warning_label.isVisible()


@pytest.mark.gui
def test_escape_hatch_checkbox_hidden_when_touch_device_present(qtbot):
    """When touch_device is a valid path, the escape-hatch checkbox is hidden.

    Spec: escape-hatch UX — checkbox hidden in normal flow.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device("/dev/input/event8")

    assert not screen.escape_hatch_checkbox.isVisible()


@pytest.mark.gui
def test_escape_hatch_warning_label_hidden_when_touch_device_present(qtbot):
    """When touch_device is a valid path, the warning label is hidden.

    Spec: escape-hatch UX — warning hidden in normal flow.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device("/dev/input/event8")

    assert not screen.no_touch_warning_label.isVisible()


# ---------------------------------------------------------------------------
# Checkbox re-enables / re-disables Record button
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_escape_hatch_checked_re_enables_record(qtbot):
    """Checking the escape-hatch checkbox re-enables Record (with form filled).

    Spec: escape-hatch UX — checkbox checked → Record re-enabled.
    """
    from PySide6.QtCore import Qt

    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("emulator-5554")
    _fill_form(screen)
    screen.set_touch_device(None)

    # Precondition: Record is disabled
    assert not screen.record_button.isEnabled()

    # Check the escape-hatch checkbox
    screen.escape_hatch_checkbox.setCheckState(Qt.CheckState.Checked)

    assert screen.record_button.isEnabled()


@pytest.mark.gui
def test_escape_hatch_unchecked_disables_record_again(qtbot):
    """Unchecking the escape-hatch checkbox re-disables Record when touch_device is None.

    Spec: escape-hatch UX — checkbox unchecked → Record disabled again.
    """
    from PySide6.QtCore import Qt

    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("emulator-5554")
    _fill_form(screen)
    screen.set_touch_device(None)

    # Check then uncheck
    screen.escape_hatch_checkbox.setCheckState(Qt.CheckState.Checked)
    assert screen.record_button.isEnabled()

    screen.escape_hatch_checkbox.setCheckState(Qt.CheckState.Unchecked)
    assert not screen.record_button.isEnabled()


# ---------------------------------------------------------------------------
# escape_hatch_active property
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_escape_hatch_active_false_by_default(qtbot):
    """escape_hatch_active is False when checkbox is unchecked.

    Spec: escape-hatch UX — property exposes checkbox state for MainWindow.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device(None)

    assert screen.escape_hatch_active is False


@pytest.mark.gui
def test_escape_hatch_active_true_when_checkbox_checked(qtbot):
    """escape_hatch_active is True when checkbox is checked.

    Spec: escape-hatch UX — MainWindow reads this to decide monitor spawn.
    """
    from PySide6.QtCore import Qt

    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device(None)
    screen.escape_hatch_checkbox.setCheckState(Qt.CheckState.Checked)

    assert screen.escape_hatch_active is True


@pytest.mark.gui
def test_escape_hatch_active_false_when_touch_device_present(qtbot):
    """escape_hatch_active is False when touch_device is present (checkbox irrelevant).

    Spec: escape-hatch UX — normal flow, no escape hatch needed.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device("/dev/input/event8")

    assert screen.escape_hatch_active is False


# ---------------------------------------------------------------------------
# Warning label has meaningful text
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_no_touch_warning_label_contains_warning_text(qtbot):
    """no_touch_warning_label has a non-empty warning text when shown.

    Spec: escape-hatch UX — user must see a meaningful message.
    """
    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_touch_device(None)

    assert screen.no_touch_warning_label.text() != ""


# ---------------------------------------------------------------------------
# Triangulation: escape-hatch resets when touch device is set after None
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_escape_hatch_resets_when_touch_device_set(qtbot):
    """After set_touch_device(path), escape-hatch state resets: checkbox hidden, active=False.

    Triangulation: device appears after initially being absent.
    """
    from PySide6.QtCore import Qt

    screen = IdleScreen()
    qtbot.addWidget(screen)

    screen.set_device_status("emulator-5554")
    _fill_form(screen)
    screen.set_touch_device(None)
    screen.escape_hatch_checkbox.setCheckState(Qt.CheckState.Checked)

    # Now a device appears
    screen.set_touch_device("/dev/input/event8")

    assert not screen.escape_hatch_checkbox.isVisible()
    assert screen.escape_hatch_active is False
    # Record button should be enabled because touch device is present and form is valid
    assert screen.record_button.isEnabled()
