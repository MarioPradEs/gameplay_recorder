"""Done state screen widget.

Spec: Requirement "ZIP Packaging", Scenario "Valid ZIP produced" —
Done screen shows the path to the produced ZIP.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DoneScreen(QWidget):
    """Done state screen — ZIP path display, Open Folder, and Record Again buttons.

    Attributes:
        zip_path_label (QLabel): shows the path to the produced ZIP file.
        open_folder_button (QPushButton): opens the OS file manager at the ZIP parent.
        record_again_button (QPushButton): transitions back to IDLE.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.zip_path_label = QLabel("", self)
        self.open_folder_button = QPushButton("Open Folder", self)
        self.record_again_button = QPushButton("Record Again", self)

        # Keep private aliases for backward-compat with any existing tests
        # that may reference the private names.
        self._open_folder_button = self.open_folder_button
        self._record_again_button = self.record_again_button

        # Internal state: current ZIP path (set via set_zip_path).
        self._zip_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(self.zip_path_label)
        layout.addWidget(self.open_folder_button)
        layout.addWidget(self.record_again_button)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_zip_path(self, path: Path) -> None:
        """Update the ZIP path label and store the path for folder reveal.

        Args:
            path: :class:`pathlib.Path` to the produced ZIP file.

        The label text is set to the string representation of *path*,
        so that the filename is visible (e.g. ``"foo.zip"`` will appear
        somewhere in the label text).
        """
        self._zip_path = path
        self.zip_path_label.setText(str(path))
