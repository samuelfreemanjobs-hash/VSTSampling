"""Thread-safe render job queue with JSON persistence."""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Statuses a job can be restarted from when a saved queue is reloaded.
_RESUMABLE = {JobStatus.RUNNING, JobStatus.PAUSED}


@dataclass
class Job:
    plugin: str
    bank: str = ""
    preset: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0  # 0.0 - 1.0
    message: str = ""
    error: str = ""
    settings_override: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.plugin, self.bank, self.preset) if p]
        return " / ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        d = dict(d)
        d["status"] = JobStatus(d.get("status", "pending"))
        return cls(**d)


class QueueManager:
    """Owns the ordered job list. All public methods are thread-safe.

    Listeners are called with no arguments after any mutation; UI code
    subscribes to refresh itself. Listeners run on the mutating thread,
    so Tk consumers should marshal back to the main loop via `after()`.
    """

    def __init__(self, save_path: Path | None = None) -> None:
        self._jobs: list[Job] = []
        self._lock = threading.RLock()
        self._save_path = save_path
        self._listeners: list[Callable[[], None]] = []
        self.pause_event = threading.Event()  # set = paused
        self.cancel_event = threading.Event()

    # -- subscription -------------------------------------------------

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # -- job CRUD -----------------------------------------------------

    def add(self, job: Job) -> Job:
        with self._lock:
            self._jobs.append(job)
        self._notify()
        return job

    def remove(self, job_id: str) -> bool:
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j.id != job_id]
            removed = len(self._jobs) != before
        if removed:
            self._notify()
        return removed

    def clear_finished(self) -> int:
        done = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j.status not in done]
            n = before - len(self._jobs)
        if n:
            self._notify()
        return n

    def move(self, job_id: str, offset: int) -> bool:
        """Move a job up (offset<0) or down (offset>0) in the queue."""
        with self._lock:
            idx = next((i for i, j in enumerate(self._jobs) if j.id == job_id), None)
            if idx is None:
                return False
            new_idx = max(0, min(len(self._jobs) - 1, idx + offset))
            if new_idx == idx:
                return False
            job = self._jobs.pop(idx)
            self._jobs.insert(new_idx, job)
        self._notify()
        return True

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs if j.id == job_id), None)

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs)

    def next_pending(self) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs if j.status == JobStatus.PENDING), None)

    # -- job state updates (called from worker threads) ---------------

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: float | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = next((j for j in self._jobs if j.id == job_id), None)
            if job is None:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = max(0.0, min(1.0, progress))
            if message is not None:
                job.message = message
            if error is not None:
                job.error = error
        self._notify()

    # -- run control --------------------------------------------------

    def pause(self) -> None:
        self.pause_event.set()
        self._notify()

    def resume(self) -> None:
        self.pause_event.clear()
        self._notify()

    def cancel_all(self) -> None:
        self.cancel_event.set()
        with self._lock:
            for job in self._jobs:
                if job.status in (JobStatus.PENDING, JobStatus.PAUSED):
                    job.status = JobStatus.CANCELLED
        self._notify()

    def reset_run_flags(self) -> None:
        self.pause_event.clear()
        self.cancel_event.clear()

    @property
    def is_paused(self) -> bool:
        return self.pause_event.is_set()

    # -- persistence --------------------------------------------------

    def save(self, path: Path | None = None) -> Path:
        target = path or self._save_path
        if target is None:
            raise ValueError("No save path configured")
        with self._lock:
            payload = [j.to_dict() for j in self._jobs]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def load(self, path: Path | None = None) -> int:
        source = path or self._save_path
        if source is None or not source.exists():
            return 0
        payload = json.loads(source.read_text(encoding="utf-8"))
        jobs = [Job.from_dict(d) for d in payload]
        # Jobs that were mid-flight when the app died restart from pending.
        for job in jobs:
            if job.status in _RESUMABLE:
                job.status = JobStatus.PENDING
                job.progress = 0.0
        with self._lock:
            self._jobs = jobs
        self._notify()
        return len(jobs)
