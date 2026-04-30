"""Idle state screen widget.

Spec: Requirement "GUI State Machine" — IDLE state.
Exposes the game dropdown, player name field, Record button, and update banner.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
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


class IdleScreen(QWidget):
    """Idle state screen — game form, Record button, and optional update banner.

    Attributes:
        game_dropdown (QComboBox): game selector.
        player_name_field (QLineEdit): player name input.
        record_button (QPushButton): starts recording; disabled until a valid
            device serial is set via :meth:`set_device_status`.
        update_banner (_BannerLabel): version-update notification; hidden by
            default.  ``isVisible()`` reflects the last call to
            :meth:`set_update_available`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Widgets
        self.update_banner = _BannerLabel("", self)
        self.update_banner.setVisible(False)

        self.game_dropdown = QComboBox(self)
        self.game_dropdown.addItem("zombie_gore")

        self.player_name_field = QLineEdit(self)

        self.record_button = QPushButton("Record", self)
        self.record_button.setEnabled(False)  # requires a device

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.update_banner)
        layout.addWidget(self.game_dropdown)
        layout.addWidget(self.player_name_field)
        layout.addWidget(self.record_button)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_device_status(self, serial: str | None) -> None:
        """Enable or disable the Record button based on device availability.

        Args:
            serial: A non-empty device serial string means the device is ready;
                ``None`` means no device — button is disabled.
        """
        self.record_button.setEnabled(serial is not None)

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
