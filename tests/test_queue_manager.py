"""Tests for core.queue_manager."""
from __future__ import annotations

import threading
from pathlib import Path

from core.queue_manager import Job, JobStatus, QueueManager


def make_qm(tmp_path: Path) -> QueueManager:
    return QueueManager(save_path=tmp_path / "queue.json")


def test_add_remove_and_order(tmp_path: Path) -> None:
    qm = make_qm(tmp_path)
    a = qm.add(Job(plugin="Omnisphere", bank="Factory A"))
    b = qm.add(Job(plugin="Serum", bank="Factory"))
    assert [j.id for j in qm.jobs()] == [a.id, b.id]
    assert qm.remove(a.id)
    assert not qm.remove("nonexistent")
    assert [j.id for j in qm.jobs()] == [b.id]


def test_move_clamps_at_edges(tmp_path: Path) -> None:
    qm = make_qm(tmp_path)
    a = qm.add(Job(plugin="A"))
    b = qm.add(Job(plugin="B"))
    c = qm.add(Job(plugin="C"))
    assert qm.move(c.id, -1)
    assert [j.plugin for j in qm.jobs()] == ["A", "C", "B"]
    assert not qm.move(a.id, -1)  # already at top
    assert qm.move(a.id, 5)  # clamped to bottom
    assert [j.plugin for j in qm.jobs()] == ["C", "B", "A"]


def test_update_and_progress_clamp(tmp_path: Path) -> None:
    qm = make_qm(tmp_path)
    a = qm.add(Job(plugin="A"))
    qm.update(a.id, status=JobStatus.RUNNING, progress=1.7, message="rendering")
    job = qm.get(a.id)
    assert job is not None
    assert job.status == JobStatus.RUNNING
    assert job.progress == 1.0
    assert job.message == "rendering"


def test_save_load_roundtrip_resets_running(tmp_path: Path) -> None:
    qm = make_qm(tmp_path)
    a = qm.add(Job(plugin="A"))
    qm.add(Job(plugin="B"))
    qm.update(a.id, status=JobStatus.RUNNING, progress=0.5)
    qm.save()

    qm2 = make_qm(tmp_path)
    assert qm2.load() == 2
    restored = qm2.get(a.id)
    assert restored is not None
    assert restored.status == JobStatus.PENDING  # mid-flight job restarts
    assert restored.progress == 0.0


def test_cancel_all_marks_pending_jobs(tmp_path: Path) -> None:
    qm = make_qm(tmp_path)
    a = qm.add(Job(plugin="A"))
    b = qm.add(Job(plugin="B"))
    qm.update(a.id, status=JobStatus.COMPLETED)
    qm.cancel_all()
    assert qm.get(a.id).status == JobStatus.COMPLETED
    assert qm.get(b.id).status == JobStatus.CANCELLED
    assert qm.cancel_event.is_set()
    qm.reset_run_flags()
    assert not qm.cancel_event.is_set()


def test_next_pending_and_clear_finished(tmp_path: Path) -> None:
    qm = make_qm(tmp_path)
    a = qm.add(Job(plugin="A"))
    b = qm.add(Job(plugin="B"))
    qm.update(a.id, status=JobStatus.COMPLETED)
    nxt = qm.next_pending()
    assert nxt is not None and nxt.id == b.id
    assert qm.clear_finished() == 1
    assert len(qm.jobs()) == 1


def test_concurrent_adds_are_safe(tmp_path: Path) -> None:
    qm = make_qm(tmp_path)

    def add_many() -> None:
        for _ in range(50):
            qm.add(Job(plugin="X"))

    threads = [threading.Thread(target=add_many) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(qm.jobs()) == 200
