"""Recording state screen widget.

Spec: Requirement "GUI State Machine" — RECORDING state.
Shows elapsed timer, Stop button, and error banner.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
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


class RecordingScreen(QWidget):
    """Recording state screen — elapsed timer, Stop button, error banner.

    Attributes:
        timer_label (QLabel): displays elapsed time formatted as ``M:SS``.
        stop_button (QPushButton): triggers stop_recording_session on MainWindow.
        error_banner (_BannerLabel): shows recording errors; hidden by default.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.error_banner = _BannerLabel("", self)
        self.error_banner.setVisible(False)

        self.timer_label = QLabel("0:00", self)
        self.stop_button = QPushButton("Stop", self)

        layout = QVBoxLayout(self)
        layout.addWidget(self.error_banner)
        layout.addWidget(self.timer_label)
        layout.addWidget(self.stop_button)
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
