"""UI package for gameplay_recorder.

Exports the 4 screen widgets used by the QStackedWidget state machine.
"""

from gameplay_recorder.ui.done_screen import DoneScreen
from gameplay_recorder.ui.idle_screen import IdleScreen
from gameplay_recorder.ui.packaging_screen import PackagingScreen
from gameplay_recorder.ui.recording_screen import RecordingScreen

__all__ = ["DoneScreen", "IdleScreen", "PackagingScreen", "RecordingScreen"]
