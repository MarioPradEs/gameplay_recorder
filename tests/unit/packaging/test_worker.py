"""RED phase — Phase 6.1: PackagingWorker post-scrcpy-pivot contract tests.

Tests that lock in the contract for PackagingWorker after the scrcpy pivot:
- No segments= parameter required
- No concat_segments() call in run()

These fail RED because PackagingWorker still requires segments as first positional arg.
GREEN in Phase 6.2 will remove that parameter and the concat call.
"""

from __future__ import annotations


def test_packaging_worker_no_longer_takes_segments_param(tmp_path):
    """After scrcpy pivot, PackagingWorker should not require a segments parameter."""
    from gameplay_recorder.packaging.worker import PackagingWorker

    session_dir = tmp_path / "session"
    session_dir.mkdir()
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    meta = {"session_id": "test", "device": {"serial": "test"}}

    # Should construct without segments= kwarg
    worker = PackagingWorker(
        session_dir=session_dir,
        meta=meta,
        output_dir=output_dir,
    )
    assert worker is not None


def test_packaging_worker_does_not_call_concat_segments(tmp_path, monkeypatch):
    """After scrcpy pivot, PackagingWorker.run() must not invoke concat_segments."""
    from gameplay_recorder.packaging import worker as worker_mod
    from gameplay_recorder.packaging.worker import PackagingWorker

    concat_called = []
    if hasattr(worker_mod, "concat_segments"):
        monkeypatch.setattr(
            worker_mod,
            "concat_segments",
            lambda *a, **kw: concat_called.append(True),
        )

    session_dir = tmp_path / "session"
    session_dir.mkdir()
    # Simulate single-file recording produced by ScrcpyRecorder
    (session_dir / "gameplay.mp4").write_bytes(b"fake mp4")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    meta = {"session_id": "test", "device": {"serial": "test"}}

    worker = PackagingWorker(
        session_dir=session_dir,
        meta=meta,
        output_dir=output_dir,
    )
    # Run synchronously (avoid QThread machinery)
    try:
        worker.run()
    except Exception:
        pass  # We only care that concat was NOT called

    assert concat_called == [], "concat_segments must not be invoked post-pivot"
