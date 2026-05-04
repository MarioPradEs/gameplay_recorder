"""EventPersister — QThread that drains TouchEventMonitor and writes events.jsonl.

Polls the monitor queue every `drain_interval_ms`, appends each drained event as
a single JSON Lines record to `output_path`, and flushes after each batch so
crashes lose at most one drain interval of events.

This is the consumer side of the producer/consumer pair with TouchEventMonitor.
TouchEventMonitor enqueues RawTouchEvent objects from `getevent` parsing;
EventPersister drains the queue and persists to disk in the format expected by
`packaging/zipper.py` and validated by `packaging/validation.py`.

Phase 2.2: edge cases — final drain after interruption, error/finished_clean
signals, defensive try/except/finally around all I/O.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from gameplay_recorder.capture.event_monitor import TouchEventMonitor
    from gameplay_recorder.models.touch_event import RawTouchEvent

logger = logging.getLogger(__name__)


class EventPersister(QThread):
    """Drains a TouchEventMonitor and persists events to a JSONL file."""

    # Emitted on any I/O failure during run(). The application thread can connect
    # to surface the error in UI; the persister itself logs the exception.
    error = Signal(str)

    # Emitted when run() exits, with the total number of events written.
    # Always emitted exactly once, regardless of normal exit or error path.
    finished_clean = Signal(int)

    def __init__(
        self,
        monitor: "TouchEventMonitor",
        output_path: Path,
        drain_interval_ms: int = 250,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._output_path = Path(output_path)
        self._drain_interval_ms = drain_interval_ms

    def run(self) -> None:
        total = 0
        try:
            with self._output_path.open("a", encoding="utf-8") as fh:
                while not self.isInterruptionRequested():
                    events = self._monitor.drain()
                    for ev in events:
                        fh.write(self._format_event(ev) + "\n")
                    if events:
                        fh.flush()
                        total += len(events)
                    self.msleep(self._drain_interval_ms)

                # Final drain after interruption — captures events that arrived
                # between the last in-loop drain and the interruption request.
                final_events = self._monitor.drain()
                for ev in final_events:
                    fh.write(self._format_event(ev) + "\n")
                if final_events:
                    fh.flush()
                    total += len(final_events)
        except Exception as exc:  # noqa: BLE001 — boundary; we re-emit and log
            logger.exception("EventPersister: I/O error during run()")
            self.error.emit(str(exc))
        finally:
            self.finished_clean.emit(total)

    @staticmethod
    def _format_event(ev: "RawTouchEvent") -> str:
        """Serialize a RawTouchEvent to a single JSON line with the 5-field whitelist."""
        return json.dumps(
            {
                "ts": ev.ts,
                "type": ev.type,
                "x": ev.x,
                "y": ev.y,
                "slot": ev.slot,
            }
        )
