"""Tests for the background job queue."""

import pytest

from ultralearn import jobs
from ultralearn.db import KnowledgeDB
from ultralearn.providers import ManualProvider, ProviderError


@pytest.fixture
def db(tmp_path):
    database = KnowledgeDB(tmp_path / "jobs.db")
    database.initialize()
    return database


@pytest.fixture
def registry():
    """Keep test handlers out of the real registry."""

    original = dict(jobs._HANDLERS)
    yield jobs._HANDLERS
    jobs._HANDLERS.clear()
    jobs._HANDLERS.update(original)


def test_queued_job_runs_and_records_its_result(db, registry):
    registry["demo"] = lambda database, provider, payload, report: {"doubled": payload["n"] * 2}

    job_id = db.enqueue_job("demo", {"n": 21}, label="Demo")
    worker = jobs.JobWorker(db, ManualProvider)
    assert worker.run_once() is True

    job = db.get_job(job_id)
    assert job["status"] == "succeeded"
    assert job["result"] == {"doubled": 42}
    assert job["progress"] == 1.0


def test_worker_reports_no_work_when_queue_is_empty(db):
    assert jobs.JobWorker(db, ManualProvider).run_once() is False


def test_progress_is_visible_while_the_job_runs(db, registry):
    """Progress must be readable mid-flight, which is what the UI polls."""

    observed: list[tuple[float, str]] = []

    def handler(database, provider, payload, report):
        report(0.5, "Halfway")
        running = database.list_jobs(active_only=True)[0]
        observed.append((running["progress"], running["detail"]))
        return {}

    registry["demo"] = handler
    db.enqueue_job("demo", {})
    jobs.JobWorker(db, ManualProvider).run_once()

    assert observed == [(0.5, "Halfway")]


def test_provider_errors_surface_as_the_job_error(db, registry):
    def handler(database, provider, payload, report):
        raise ProviderError("Claude Code is not logged in.")

    registry["demo"] = handler
    job_id = db.enqueue_job("demo", {})
    jobs.JobWorker(db, ManualProvider).run_once()

    job = db.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error"] == "Claude Code is not logged in."


def test_unexpected_exceptions_fail_the_job_not_the_worker(db, registry):
    def handler(database, provider, payload, report):
        raise ZeroDivisionError("boom")

    registry["demo"] = handler
    job_id = db.enqueue_job("demo", {})
    worker = jobs.JobWorker(db, ManualProvider)
    worker.run_once()

    assert db.get_job(job_id)["status"] == "failed"
    assert "ZeroDivisionError" in db.get_job(job_id)["error"]
    # The worker is still usable afterwards.
    assert worker.run_once() is False


def test_unknown_job_kind_fails_cleanly(db):
    job_id = db.enqueue_job("nonexistent", {})
    jobs.JobWorker(db, ManualProvider).run_once()
    assert "No handler registered" in db.get_job(job_id)["error"]


def test_a_job_is_only_claimed_once(db, registry):
    registry["demo"] = lambda database, provider, payload, report: {}
    db.enqueue_job("demo", {})

    first = db.claim_next_job()
    second = db.claim_next_job()
    assert first is not None
    assert second is None


def test_jobs_stranded_by_a_crash_are_requeued(db, registry):
    registry["demo"] = lambda database, provider, payload, report: {}
    job_id = db.enqueue_job("demo", {})
    db.claim_next_job()
    assert db.get_job(job_id)["status"] == "running"

    assert db.requeue_stale_jobs() == 1
    assert db.get_job(job_id)["status"] == "queued"


def test_active_only_filters_out_finished_jobs(db, registry):
    registry["demo"] = lambda database, provider, payload, report: {}
    db.enqueue_job("demo", {})
    jobs.JobWorker(db, ManualProvider).run_once()
    db.enqueue_job("demo", {})

    assert len(db.list_jobs()) == 2
    assert len(db.list_jobs(active_only=True)) == 1
