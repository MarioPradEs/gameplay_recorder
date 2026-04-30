"""Recording state screen widget.

Spec: Requirement "GUI State Machine" — RECORDING state.
Shows elapsed timer, segment counter, and Stop button.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class RecordingScreen(QWidget):
    """Recording state screen — elapsed timer, segment counter, Stop button.

    Attributes:
        timer_label (QLabel): displays elapsed time formatted as ``M:SS``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.timer_label = QLabel("0:00", self)
        self._segment_label = QLabel("Segment: 0", self)
        self._stop_button = QPushButton("Stop", self)

        layout = QVBoxLayout(self)
        layout.addWidget(self.timer_label)
        layout.addWidget(self._segment_label)
        layout.addWidget(self._stop_button)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_elapsed(self, seconds: int) -> None:
        """Update the timer label with *seconds* elapsed.

        Args:
            seconds: Total elapsed seconds (non-negative integer).

        The label is formatted as ``M:SS`` (e.g. ``5`` → ``"0:05"``).
        """
        minutes, secs = divmod(seconds, 60)
        self.timer_label.setText(f"{minutes}:{secs:02d}")
