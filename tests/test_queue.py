"""The Postgres work queue, including the concurrency property it rests on.

Choosing Postgres over Redis/Celery is only defensible if `SKIP LOCKED`
actually does what the comment claims, so that is tested with two real
concurrent transactions rather than taken on faith.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.exc import OperationalError

import pytest

from db.base import SessionFactory
from db.models import Job, JobState, Org, Upload
from worker import queue, run


@pytest.fixture
def org_and_uploads():
    """An org with three uploads ready to be queued."""
    db = SessionFactory()
    org = Org(name="Queue Co")
    db.add(org)
    db.flush()
    ups = []
    for i in range(3):
        u = Upload(org_id=org.id, filename=f"f{i}.csv", size_bytes=10,
                   storage_key=f"{org.id}/f{i}.csv")
        db.add(u)
        ups.append(u)
    db.commit()
    yield db, org, ups
    db.close()


class TestEnqueue:
    def test_enqueue_creates_a_queued_job(self, org_and_uploads):
        db, org, ups = org_and_uploads
        job = queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()
        assert job.state is JobState.QUEUED
        assert job.attempts == 0

    def test_the_same_upload_cannot_be_queued_twice(self, org_and_uploads):
        """jobs.upload_id is UNIQUE — duplicate work should be impossible by
        construction, not by remembering to check."""
        from sqlalchemy.exc import IntegrityError

        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()
        # The violation surfaces at enqueue's own flush, not at commit — the
        # duplicate never even reaches a transaction boundary.
        with pytest.raises(IntegrityError):
            queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.rollback()


class TestClaim:
    def test_claim_marks_running_and_records_the_worker(self, org_and_uploads):
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()

        job = queue.claim(db, "worker-a")
        assert job is not None
        assert job.state is JobState.RUNNING
        assert job.locked_by == "worker-a"
        assert job.attempts == 1
        db.commit()

    def test_empty_queue_returns_none(self, org_and_uploads):
        db, _org, _ups = org_and_uploads
        assert queue.claim(db, "worker-a") is None

    def test_a_job_scheduled_for_later_is_not_claimed(self, org_and_uploads):
        """Backoff has to actually hold the job back, or a retry storm is one
        failing file away."""
        db, org, ups = org_and_uploads
        job = queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        job.run_after = queue._now() + timedelta(minutes=5)
        db.commit()
        assert queue.claim(db, "worker-a") is None

    def test_two_concurrent_workers_claim_different_jobs(self, org_and_uploads):
        """The property that justifies not using a broker.

        Two open transactions claim simultaneously; SKIP LOCKED must hand them
        different rows rather than blocking the second until the first commits.
        """
        db, org, ups = org_and_uploads
        for u in ups[:2]:
            queue.enqueue(db, org_id=org.id, upload_id=u.id)
        db.commit()

        a, b = SessionFactory(), SessionFactory()
        try:
            job_a = queue.claim(a, "worker-a")     # transaction A holds its row
            job_b = queue.claim(b, "worker-b")     # must not block, must differ
            assert job_a is not None and job_b is not None
            assert job_a.id != job_b.id, "two workers claimed the same job"
            a.commit()
            b.commit()
        finally:
            a.close()
            b.close()

    def test_a_single_job_goes_to_exactly_one_worker(self, org_and_uploads):
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()

        a, b = SessionFactory(), SessionFactory()
        try:
            job_a = queue.claim(a, "worker-a")
            job_b = queue.claim(b, "worker-b")     # row is locked; skip it
            assert job_a is not None
            assert job_b is None, "the same job was handed to two workers"
            a.commit()
        finally:
            a.close()
            b.close()


class TestFailureHandling:
    def test_a_retryable_failure_requeues_with_backoff(self, org_and_uploads):
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()
        job = queue.claim(db, "worker-a")
        before = queue._now()
        queue.fail(db, job, "transient network blip")
        db.commit()

        assert job.state is JobState.QUEUED
        assert job.run_after > before, "a retry must be delayed, not immediate"
        assert job.locked_by is None
        assert "transient" in job.last_error

    def test_a_non_retryable_failure_fails_immediately(self, org_and_uploads):
        """Retrying a file that will never parse only delays telling the user."""
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()
        job = queue.claim(db, "worker-a")
        queue.fail(db, job, "not a spreadsheet", retryable=False)
        db.commit()
        assert job.state is JobState.FAILED

    def test_attempts_are_exhausted_then_it_fails(self, org_and_uploads):
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id, max_attempts=2)
        db.commit()
        for _ in range(2):
            job = queue.claim(db, "worker-a")
            assert job is not None
            queue.fail(db, job, "keeps breaking")
            # Clear the backoff AFTER fail(), which is what sets it — doing it
            # before just gets overwritten.
            job.run_after = func.now()
            db.commit()
        assert job.state is JobState.FAILED
        assert job.attempts == 2

    def test_complete_clears_the_lock(self, org_and_uploads):
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()
        job = queue.claim(db, "worker-a")
        queue.complete(db, job)
        db.commit()
        assert job.state is JobState.DONE
        assert job.locked_by is None


class TestStaleReclaim:
    def test_a_job_abandoned_by_a_dead_worker_is_reclaimed(self, org_and_uploads):
        """Without this, a crashed worker leaves the upload hanging forever —
        a silent stall, which is worse than a visible error."""
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()
        job = queue.claim(db, "worker-that-dies")
        job.locked_at = queue._now() - timedelta(hours=1)
        db.commit()

        assert queue.reclaim_stale(db) == 1
        db.commit()
        assert job.state is JobState.QUEUED
        assert "stopped responding" in job.last_error

    def test_a_healthy_running_job_is_left_alone(self, org_and_uploads):
        db, org, ups = org_and_uploads
        queue.enqueue(db, org_id=org.id, upload_id=ups[0].id)
        db.commit()
        queue.claim(db, "busy-worker")
        db.commit()
        assert queue.reclaim_stale(db) == 0


def test_depth_reports_by_state(org_and_uploads):
    db, org, ups = org_and_uploads
    for u in ups:
        queue.enqueue(db, org_id=org.id, upload_id=u.id)
    db.commit()
    queue.claim(db, "worker-a")
    db.commit()
    d = queue.depth(db)
    assert d.get("running") == 1
    assert d.get("queued") == 2


class TestSchemaWait:
    """The worker boots beside the migration that creates its tables.

    Regression: on the first Fly deploy the worker started ~6s before the api
    finished `alembic upgrade head` and spent those polls logging
    `relation "jobs" does not exist`. It self-healed, but a fresh deploy should
    not dump a traceback into the logs to get there.
    """

    def test_returns_immediately_when_schema_exists(self):
        # The test database is migrated, so this must not block at all.
        assert run.wait_for_schema(timeout=0) is True

    def test_probe_sees_the_migrated_schema(self):
        assert run._schema_present() is True

    def test_gives_up_and_starts_anyway(self, monkeypatch):
        """A migration that never lands delays the worker; it must not hang."""
        monkeypatch.setattr(run, "_schema_present", lambda: False)
        assert run.wait_for_schema(timeout=0) is False

    def test_waits_then_proceeds_once_the_table_appears(self, monkeypatch):
        """The point of the fix: poll through absence, return on arrival."""
        calls = {"n": 0}

        def appears_on_third_look() -> bool:
            calls["n"] += 1
            return calls["n"] >= 3

        monkeypatch.setattr(run, "_schema_present", appears_on_third_look)
        monkeypatch.setattr(run.time, "sleep", lambda _s: None)
        assert run.wait_for_schema(timeout=30) is True
        assert calls["n"] == 3

    def test_unreachable_database_counts_as_not_ready(self, monkeypatch):
        """A cold database is a wait, not a crash."""
        def refuse(*_a, **_k):
            raise OperationalError("connect", {}, Exception("refused"))

        monkeypatch.setattr(run.engine, "connect", refuse)
        assert run._schema_present() is False
