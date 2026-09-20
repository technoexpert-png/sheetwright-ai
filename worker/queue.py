"""A work queue in Postgres.

`SELECT ... FOR UPDATE SKIP LOCKED` is the whole trick: concurrent workers each
claim a different row without blocking one another, and a claim is part of the
same transaction as the state change, so a worker cannot take a job and then
crash before recording that it did.

Why not Redis, Celery, or SQS at this size:

- One fewer service to deploy, monitor, back up, and explain.
- The guarantee is stronger. A broker plus a separate database gives you
  at-least-once delivery across two systems that can disagree; here the claim
  and the row it refers to commit or roll back together.
- Retries, backoff, and dead-lettering are three columns rather than a
  framework.

Revisit when sustained throughput outgrows a single Postgres — not before. The
interface below is small enough that swapping the implementation later touches
only this file.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from db.models import Job, JobState

# Backoff between attempts. Short at this scale: a failure is usually a bad
# file, which a retry will not fix, so the value of a long tail is low.
RETRY_BACKOFF_SECONDS = (5, 30, 120)

# A job whose worker vanished stays RUNNING forever unless something reclaims
# it. Longer than the slowest plausible job, shorter than a user's patience.
STALE_AFTER_SECONDS = 15 * 60


def _now() -> datetime:
    """Application clock. Only for values a human reads, never for deciding
    whether a job is due — see the note on ONE CLOCK below."""
    return datetime.now(timezone.utc)


# ── ONE CLOCK ────────────────────────────────────────────────────────────────
# `jobs.run_after` is filled by the database (`server_default=now()`), so every
# comparison against it must also use the database clock. Comparing it to the
# application's clock is a real bug, not a rounding detail: the app's `now()` is
# captured before the INSERT lands, so a just-enqueued job reads as not-yet-due
# and is skipped. With a separate database host, clock skew turns that into
# jobs stalling for however far behind the app server drifts.
#
# So: schedule with `func.now()`, compare with `func.now()`. The database is
# the only clock the queue trusts.


def worker_identity() -> str:
    """Host plus a random suffix, so two workers on one machine are distinct
    and a stuck job names something a human can actually go and look at."""
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def enqueue(
    db: DbSession, *, org_id: uuid.UUID, upload_id: uuid.UUID, max_attempts: int = 3
) -> Job:
    """Queue one upload for processing.

    `jobs.upload_id` is UNIQUE, so enqueueing the same upload twice raises
    rather than silently creating duplicate work — re-running a conversion
    resets the existing job instead (see `requeue`).
    """
    job = Job(org_id=org_id, upload_id=upload_id, max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def requeue(db: DbSession, job: Job) -> Job:
    """Put a finished or failed job back, for a re-run after a human corrects
    a mapping. Attempts reset: this is a new intent, not a retry of a failure."""
    job.state = JobState.QUEUED
    job.attempts = 0
    job.last_error = None
    job.locked_at = None
    job.locked_by = None
    job.run_after = func.now()
    db.flush()
    return job


def claim(db: DbSession, worker_id: str) -> Job | None:
    """Atomically take the next due job, or return None.

    Must run inside a transaction. SKIP LOCKED makes this safe for N workers:
    each skips rows another worker already holds instead of queueing behind
    them, so throughput scales with workers rather than serializing.
    """
    job = db.scalars(
        select(Job)
        .where(Job.state == JobState.QUEUED, Job.run_after <= func.now())
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None

    job.state = JobState.RUNNING
    job.attempts += 1
    job.locked_at = func.now()
    job.locked_by = worker_id
    db.flush()
    return job


def complete(db: DbSession, job: Job) -> None:
    job.state = JobState.DONE
    job.locked_at = None
    job.locked_by = None
    job.last_error = None
    db.flush()


def fail(db: DbSession, job: Job, error: str, *, retryable: bool = True) -> None:
    """Record a failure, scheduling a retry if attempts remain.

    A non-retryable failure (an unreadable file, say) goes straight to FAILED:
    retrying a file that will never parse just delays telling the user.
    """
    job.last_error = error[:2000]
    job.locked_at = None
    job.locked_by = None

    if not retryable or job.attempts >= job.max_attempts:
        job.state = JobState.FAILED
    else:
        idx = min(job.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)
        job.state = JobState.QUEUED
        # Database clock again, so the backoff is measured against the same
        # reference the claim query reads.
        job.run_after = func.now() + timedelta(seconds=RETRY_BACKOFF_SECONDS[idx])
    db.flush()


def reclaim_stale(db: DbSession, *, older_than_seconds: int = STALE_AFTER_SECONDS) -> int:
    """Return jobs abandoned by dead workers to the queue.

    Without this a crashed worker's in-flight job is stuck in RUNNING forever
    and the upload never finishes — a silent hang, which is worse than a
    visible error.
    """
    stale = list(db.scalars(
        select(Job).where(
            Job.state == JobState.RUNNING,
            Job.locked_at < func.now() - timedelta(seconds=older_than_seconds),
        ).with_for_update(skip_locked=True)
    ))
    for job in stale:
        fail(job=job, db=db, error=f"worker {job.locked_by} stopped responding")
    return len(stale)


def depth(db: DbSession) -> dict[str, int]:
    """Queue depth by state — the metric worth putting on a dashboard."""
    rows = db.execute(select(Job.state, func.count()).group_by(Job.state)).all()
    return {state.value: n for state, n in rows}
