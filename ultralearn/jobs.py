"""Background job execution.

Every provider call runs here rather than inline, so the UI never waits on an
LLM. Work is queued in SQLite (see the ``jobs`` table) and drained by a worker
thread; the API reports progress over SSE. That is what lets ingestion of a long
chapter run while the learner is answering questions.
"""

from __future__ import annotations

import json
import threading
import traceback
from collections.abc import Callable
from typing import Any

from .db import KnowledgeDB
from .providers import Provider, ProviderError

#: Signature of a job implementation. Receives the decoded payload and a
#: progress reporter, and returns a JSON-serialisable result.
JobHandler = Callable[[KnowledgeDB, Provider, dict[str, Any], "ProgressReporter"], dict[str, Any]]

_HANDLERS: dict[str, JobHandler] = {}


class ProgressReporter:
    """Writes progress for one job back to the database."""

    def __init__(self, db: KnowledgeDB, job_id: int) -> None:
        self._db = db
        self._job_id = job_id

    def __call__(self, fraction: float, detail: str = "") -> None:
        self._db.update_job(self._job_id, progress=fraction, detail=detail)


def register(kind: str) -> Callable[[JobHandler], JobHandler]:
    """Register a handler for a job kind."""

    def decorator(handler: JobHandler) -> JobHandler:
        _HANDLERS[kind] = handler
        return handler

    return decorator


def handler_for(kind: str) -> JobHandler | None:
    return _HANDLERS.get(kind)


class JobWorker:
    """A single daemon thread draining the job queue.

    One worker is deliberate: provider calls are serialised so a burst of
    ingestion cannot saturate the CLI or interleave usage accounting.
    """

    def __init__(
        self,
        db: KnowledgeDB,
        provider_factory: Callable[[], Provider],
        poll_seconds: float = 0.5,
    ) -> None:
        self._db = db
        self._provider_factory = provider_factory
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # A job left "running" by a crash would otherwise never be picked up.
        self._db.requeue_stale_jobs()
        self._thread = threading.Thread(target=self._loop, name="ultralearn-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(self._poll_seconds)

    def run_once(self) -> bool:
        """Run at most one queued job. Returns whether work was found.

        Also the unit of execution in tests, which drive the queue synchronously
        instead of starting a thread.
        """

        row = self._db.claim_next_job()
        if row is None:
            return False

        job_id = int(row["id"])
        handler = handler_for(row["kind"])
        if handler is None:
            self._db.update_job(
                job_id, status="failed", error=f"No handler registered for job kind '{row['kind']}'."
            )
            return True

        payload = json.loads(row["payload_json"] or "{}")
        report = ProgressReporter(self._db, job_id)
        try:
            result = handler(self._db, self._provider_factory(), payload, report)
        except ProviderError as exc:
            # Expected, actionable failures (logged out, timed out, bad output):
            # report the message as-is, it is written for the learner to read.
            self._db.update_job(job_id, status="failed", error=str(exc))
        except Exception:  # noqa: BLE001 - a worker thread must never die
            self._db.update_job(job_id, status="failed", error=traceback.format_exc(limit=3))
        else:
            self._db.update_job(
                job_id, status="succeeded", progress=1.0, result=result, detail="Done"
            )
        return True
