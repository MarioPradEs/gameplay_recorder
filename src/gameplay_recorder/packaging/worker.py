"""Packaging worker for gameplay_recorder.

Runs assemble_zip in a background QThread so the UI remains responsive
during the (potentially slow) ZIP assembly step.

Design: packaging/worker.py — PackagingWorker(QThread)
Signal: finished(Path) — emitted with the produced ZIP path on success
        error(str)     — emitted with a human-readable message on failure

Spec: Requirement "Segmented Video Capture", Scenario "Stop recording" —
packaging MUST start automatically after stop without blocking the UI.
"""

from __future__ import annotations

import logging
from pathlib import Path

from gameplay_recorder.models.session import SessionMeta

logger = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:  # allow unit tests without a display
    QThread = object  # type: ignore[assignment,misc]

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *args):
            pass


class PackagingWorker(QThread):
    """Run ZIP packaging in a background thread.

    Wraps :func:`~gameplay_recorder.packaging.zipper.assemble_zip` so the
    GUI thread is never blocked.

    Signals:
        finished(Path): Emitted with the ZIP path when packaging completes.
        error(str):     Emitted with a human-readable message on failure.
    """

    finished = Signal(object)  # Path
    error = Signal(str)

    def __init__(
        self,
        session_dir: Path,
        meta: SessionMeta,
        output_dir: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_dir = Path(session_dir)
        self._meta = meta
        self._output_dir = Path(output_dir)

    # ── QThread entry point ──────────────────────────────────────────────────

    def run(self) -> None:
        """Assemble ZIP from session dir — runs in the worker thread."""
        try:
            from gameplay_recorder.packaging.zipper import assemble_zip

            zip_path = assemble_zip(self._session_dir, self._meta, self._output_dir)

            self.finished.emit(zip_path)

        except Exception as exc:  # noqa: BLE001
            logger.exception("PackagingWorker: packaging failed")
            self.error.emit(str(exc))
