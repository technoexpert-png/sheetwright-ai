"""Worker entrypoint: claim jobs, run them, report, repeat.

Run with `python -m worker.run`. One process per container; scale by running
more, which is safe because `claim()` uses SKIP LOCKED.

The loop is deliberately boring. Every interesting decision — retry policy,
backoff, stale reclaim — lives in worker/queue.py, and the conversion itself in
worker/pipeline.py. What is left here is scheduling, shutdown, and making sure
a failure in one job cannot take the process down.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from types import FrameType

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from config import settings
from db.base import SessionFactory, engine
from worker import queue
from worker.pipeline import PermanentFailure, process

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")

# How often to sweep for jobs abandoned by dead workers. Rare, because it is a
# recovery path, not a hot one.
RECLAIM_EVERY_SECONDS = 60

# On a fresh deploy the api process runs `alembic upgrade head` while the worker
# boots beside it, so the worker can reach an empty database. It deliberately
# does not migrate itself -- two processes racing the Alembic version lock is a
# worse problem than waiting -- so it waits for the schema to appear instead of
# spending its first polls logging "relation \"jobs\" does not exist".
SCHEMA_WAIT_SECONDS = 120.0


def _schema_present() -> bool:
    """True once the jobs table exists.

    A database that is not accepting connections yet counts as "not ready" and
    not as an error: on a cold start it is the same wait for the same reason.
    """
    try:
        with engine.connect() as conn:
            return conn.scalar(text("SELECT to_regclass('public.jobs')")) is not None
    except OperationalError:
        return False


def wait_for_schema(timeout: float = SCHEMA_WAIT_SECONDS) -> bool:
    """Block until migrations have created the schema. False if they never did.

    Falling through on timeout rather than exiting is deliberate. The tick loop
    already survives a missing table, so a migration that is merely slow should
    delay the worker, not crash-loop the machine.
    """
    deadline = time.monotonic() + timeout
    waited = False
    while True:
        if _schema_present():
            if waited:
                logger.info("schema ready")
            return True
        if time.monotonic() >= deadline:
            logger.warning("schema still missing after %.0fs; starting anyway", timeout)
            return False
        if not waited:
            logger.info("waiting for migrations to create the schema")
            waited = True
        time.sleep(1.0)


class Runner:
    def __init__(self) -> None:
        self.worker_id = queue.worker_identity()
        self.running = True
        self._last_reclaim = 0.0

    def request_stop(self, signum: int, _frame: FrameType | None) -> None:
        """Finish the current job, then exit.

        SIGTERM is how a platform asks a container to stop before killing it.
        Draining rather than dying mid-job means the claimed row is released
        cleanly instead of waiting out the stale-reclaim window.
        """
        logger.info("signal %s received; finishing current job then exiting", signum)
        self.running = False

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        wait_for_schema()
        logger.info("worker %s started (poll %.1fs)", self.worker_id,
                    settings().worker_poll_seconds)

        while self.running:
            try:
                did_work = self._tick()
            except Exception:  # noqa: BLE001
                # A broken job must never kill the worker: the next poll should
                # still happen. Sleep a little so a persistent fault does not
                # spin the CPU.
                logger.exception("worker tick failed")
                time.sleep(settings().worker_poll_seconds)
                continue

            if not did_work:
                time.sleep(settings().worker_poll_seconds)

        logger.info("worker %s stopped", self.worker_id)
        return 0

    def _tick(self) -> bool:
        """Claim and run at most one job. Returns True if work was done."""
        self._maybe_reclaim()

        db = SessionFactory()
        try:
            job = queue.claim(db, self.worker_id)
            if job is None:
                db.commit()
                return False

            # The claim is committed before the work starts, so a crash mid-job
            # leaves the row visibly RUNNING for stale reclaim rather than
            # rolling back and letting another worker take it concurrently.
            upload_id = job.upload_id
            db.commit()

            logger.info("job %s claimed for upload %s", job.id, upload_id)
            try:
                process(db, upload_id)
                queue.complete(db, job)
                db.commit()
            except PermanentFailure as exc:
                # pipeline.process already recorded the user-facing error.
                queue.fail(db, job, str(exc), retryable=False)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                # Re-fetch: the rollback detached whatever we were holding.
                fresh = db.get(type(job), job.id)
                if fresh is not None:
                    queue.fail(db, fresh, repr(exc), retryable=True)
                    db.commit()
            return True
        finally:
            db.close()

    def _maybe_reclaim(self) -> None:
        now = time.monotonic()
        if now - self._last_reclaim < RECLAIM_EVERY_SECONDS:
            return
        self._last_reclaim = now
        db = SessionFactory()
        try:
            n = queue.reclaim_stale(db)
            db.commit()
            if n:
                logger.warning("reclaimed %d stale job(s)", n)
        finally:
            db.close()


if __name__ == "__main__":
    sys.exit(Runner().run())
