"""Packaging state screen widget.

Spec: Requirement "GUI State Machine" — PACKAGING state.
Shows a progress indicator; Stop button is disabled during packaging.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PackagingScreen(QWidget):
    """Packaging state screen — progress indicator with Stop button disabled.

    Attributes:
        progress_label (QLabel): shows packaging status message.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.progress_label = QLabel("Packaging…", self)
        self._stop_button = QPushButton("Stop", self)
        self._stop_button.setEnabled(False)  # spec: disabled during packaging

        layout = QVBoxLayout(self)
        layout.addWidget(self.progress_label)
        layout.addWidget(self._stop_button)
        self.setLayout(layout)
