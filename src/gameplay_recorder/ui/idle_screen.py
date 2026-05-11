"""Idle state screen widget.

Spec: Requirement "GUI State Machine" — IDLE state.
Exposes the game dropdown, version field, player name field, device status label,
Record button, and update banner.

Phase 14b: Rebuilt with QFormLayout for labels-on-left UX, display map for
dropdown (Zombie Gore → zombie_gore), tooltips on all form fields, and
device_status_label that reflects the connected device serial.

Phase 14c: Added form validation (_validate_form), _current_serial storage,
error_banner for packaging errors.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _BannerLabel(QLabel):
    """QLabel that tracks its own explicit visibility independently of the parent chain.

    Qt's ``isVisible()`` returns ``False`` whenever any ancestor is hidden (including
    when the parent widget has never been ``show()``-ed, which is the common case in
    unit tests).  This subclass overrides ``isVisible()`` to return the value last
    passed to ``setVisible()``, so that tests can assert banner visibility without
    needing to show the parent window.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._explicitly_visible: bool = False

    def setVisible(self, visible: bool) -> None:  # type: ignore[override]
        self._explicitly_visible = visible
        super().setVisible(visible)

    def isVisible(self) -> bool:  # type: ignore[override]
        return self._explicitly_visible


class _TrackableCheckBox(QCheckBox):
    """QCheckBox that tracks its own explicit visibility independently of the parent chain.

    Same rationale as _BannerLabel: Qt's ``isVisible()`` propagates through the parent
    chain, so unit tests that never ``show()`` the window always see False.  This subclass
    overrides ``isVisible()`` to reflect the last explicit ``setVisible()`` call.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._explicitly_visible: bool = False

    def setVisible(self, visible: bool) -> None:  # type: ignore[override]
        self._explicitly_visible = visible
        super().setVisible(visible)

    def isVisible(self) -> bool:  # type: ignore[override]
        return self._explicitly_visible


#: Maps game_id (snake_case, stored in session_meta.json) → display name (human-readable).
#: DO NOT use currentText() as the game_id — always use currentData().
_GAME_DISPLAY_MAP: list[tuple[str, str]] = [
    ("zombie_gore", "Zombie Gore"),
]


class IdleScreen(QWidget):
    """Idle state screen — game form, Record button, and optional update banner.

    Layout (QFormLayout with labels on the left):
        update_banner   — full-width banner (outside the form, at the top)
        Game:           | game_dropdown
        Version:        | version_field
        Player:         | player_name_field
        Device:         | device_status_label
        (empty)         | record_button

    Attributes:
        game_dropdown (QComboBox): game selector.  ``currentText()`` returns the
            human-readable display name (e.g. "Zombie Gore"); ``currentData()``
            returns the snake_case ``game_id`` (e.g. ``"zombie_gore"``) that is
            persisted in ``session_meta.json``.
        version_field (QLineEdit): free-text game version input.
        player_name_field (QLineEdit): player name / alias input.
        device_status_label (QLabel): shows the connected device serial or
            "No device connected" when no device is available.
        record_button (QPushButton): starts recording; disabled until a valid
            device serial is set via :meth:`set_device_status`.
        update_banner (_BannerLabel): version-update notification; hidden by
            default.  ``isVisible()`` reflects the last call to
            :meth:`set_update_available`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ── Internal state ──────────────────────────────────────────────────
        self._current_serial: str | None = None
        self._touch_device: str | None = None

        # ── Banners (outside form layout, span full width) ──────────────────
        self.update_banner = _BannerLabel("", self)
        self.update_banner.setVisible(False)

        self.error_banner = _BannerLabel("", self)
        self.error_banner.setVisible(False)
        self.error_banner.setStyleSheet("color: #c0392b; background: #fdecea; padding: 4px;")

        # ── Escape-hatch widgets (shown only when no touch device) ──────────
        self.no_touch_warning_label = _BannerLabel(
            "⚠ No touch device detected — touch events will not be recorded.", self
        )
        self.no_touch_warning_label.setVisible(False)
        self.no_touch_warning_label.setStyleSheet(
            "color: #856404; background: #fff3cd; padding: 4px;"
        )

        self.escape_hatch_checkbox = _TrackableCheckBox(
            "Continue anyway (no touch events will be recorded)", self
        )
        self.escape_hatch_checkbox.setVisible(False)
        self.escape_hatch_checkbox.stateChanged.connect(self._validate_form)

        # ── Form widgets ────────────────────────────────────────────────────
        self.game_dropdown = QComboBox(self)
        for game_id, display_name in _GAME_DISPLAY_MAP:
            self.game_dropdown.addItem(display_name, userData=game_id)
        self.game_dropdown.setToolTip(
            "The game you are recording. The selected game's id is saved in session_meta.json."
        )

        self.version_field = QLineEdit(self)
        self.version_field.setPlaceholderText("e.g. 1.32.1")
        self.version_field.setToolTip(
            "The version of the game shown on the title screen (free text). Example: 1.32.1"
        )

        self.player_name_field = QLineEdit(self)
        self.player_name_field.setPlaceholderText("Your name")
        self.player_name_field.setToolTip(
            "Your name or alias — saved as recorded_by in session_meta.json "
            "so we know who recorded this session."
        )

        self.device_status_label = QLabel("No device connected", self)

        self.record_button = QPushButton("Record", self)
        self.record_button.setEnabled(False)  # requires a device + valid form

        # ── Layout ──────────────────────────────────────────────────────────
        form = QFormLayout()
        form.addRow("Game:", self.game_dropdown)
        form.addRow("Version:", self.version_field)
        form.addRow("Player:", self.player_name_field)
        form.addRow("Device:", self.device_status_label)
        form.addRow("", self.record_button)

        root = QVBoxLayout(self)
        root.addWidget(self.update_banner)
        root.addWidget(self.error_banner)
        root.addWidget(self.no_touch_warning_label)
        root.addWidget(self.escape_hatch_checkbox)
        root.addLayout(form)
        self.setLayout(root)

        # ── Form validation wiring ──────────────────────────────────────────
        self.version_field.textChanged.connect(self._validate_form)
        self.player_name_field.textChanged.connect(self._validate_form)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_game_id(self) -> str:
        """Return the snake_case game_id for the currently selected game.

        Always use this (or ``game_dropdown.currentData()``) as the source for
        ``game_id`` in ``session_meta.json`` — NEVER use ``currentText()``.

        Returns:
            The snake_case game identifier (e.g. ``"zombie_gore"``).
        """
        return self.game_dropdown.currentData()

    def set_device_status(self, serial: str | None) -> None:
        """Update the device status label and re-evaluate form validity.

        Args:
            serial: A non-empty device serial string means the device is ready
                (label set to ``"Device: {serial}"``; _current_serial stored).
                ``None`` means no device — label reset to ``"No device connected"``;
                _current_serial cleared; Record button disabled.
        """
        self._current_serial = serial
        if serial is not None:
            self.device_status_label.setText(f"Device: {serial}")
        else:
            self.device_status_label.setText("No device connected")
        self._validate_form()

    def _validate_form(self) -> None:
        """Enable the Record button only when all required fields are filled.

        Required: a device serial is set, version_field is non-empty, and
        player_name_field is non-empty.
        Touch device gating (Phase 4):
          - If _touch_device is set (not None): normal — no extra requirement.
          - If _touch_device is None: Record only enabled when escape_hatch_active.
        """
        touch_ok = (
            self._touch_device is not None
            or self.escape_hatch_checkbox.checkState() == Qt.CheckState.Checked
        )
        ready = (
            self._current_serial is not None
            and bool(self.version_field.text().strip())
            and bool(self.player_name_field.text().strip())
            and touch_ok
        )
        self.record_button.setEnabled(ready)

    def show_error_banner(self, message: str) -> None:
        """Show the error banner with *message*.

        Args:
            message: Human-readable error string to display.
        """
        self.error_banner.setText(message)
        self.error_banner.setVisible(True)

    def set_touch_device(self, device: str | None) -> None:
        """Update the known touch device path and re-evaluate escape-hatch widgets.

        Args:
            device: A non-None string means a touch device is available.
                ``None`` means no touch device was detected — shows warning
                and escape-hatch checkbox; blocks Record until user opts in.
        """
        self._touch_device = device
        has_device = device is not None
        # Show escape-hatch UI only when no touch device
        self.no_touch_warning_label.setVisible(not has_device)
        self.escape_hatch_checkbox.setVisible(not has_device)
        # When a device appears, uncheck the checkbox so state resets cleanly
        if has_device:
            self.escape_hatch_checkbox.setCheckState(Qt.CheckState.Unchecked)
        self._validate_form()

    @property
    def escape_hatch_active(self) -> bool:
        """Return True if the escape-hatch checkbox is checked.

        MainWindow reads this before deciding whether to spawn TouchEventMonitor.
        Only meaningful when _touch_device is None; always False when device present.
        """
        if self._touch_device is not None:
            return False
        return self.escape_hatch_checkbox.checkState() == Qt.CheckState.Checked

    def set_update_available(self, version: str | None) -> None:
        """Show or hide the update banner.

        Args:
            version: New version string (e.g. ``"0.2.0"``); ``None`` hides the banner.
        """
        if version is not None:
            self.update_banner.setText(f"Update available: {version}")
            self.update_banner.setVisible(True)
        else:
            self.update_banner.setVisible(False)
