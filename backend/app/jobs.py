"""Background jobs people start, run by the worker one at a time: score recalculations and
report exports (FR-SC3, FR-RP5).

A handler is registered per job type and receives the job; it returns the result to keep
(a count, the exported file). A failed job keeps its error and is not retried: whoever started
it can see what went wrong and start it again.
"""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import clock
from app.models import Job

log = logging.getLogger(__name__)

Handler = Callable[[Session, Job], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}
# Called after a failed job's work is rolled back, to mark what it was working on.
ON_FAILURE: dict[str, Callable[[Session, Job], None]] = {}


def handler(job_type: str, on_failure: Callable[[Session, Job], None] | None = None) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        if on_failure:
            ON_FAILURE[job_type] = on_failure
        return fn

    return register


def enqueue(db: Session, job_type: str, payload: dict[str, Any], created_by: int | None) -> Job:
    job = Job(type=job_type, payload=payload, created_by=created_by)
    db.add(job)
    db.flush()
    return job


def run_next(db: Session) -> bool:
    """Run the oldest queued job, if any. Returns whether one ran."""
    job = db.execute(
        select(Job)
        .where(Job.status == "queued", Job.type.in_(list(HANDLERS)), Job.run_after <= clock.now())
        .order_by(Job.id)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return False
    # Claim it, so a second worker started by mistake doesn't run it twice.
    claimed = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == "queued")
        .values(status="running", started_at=clock.now(), attempts=Job.attempts + 1)
    ).rowcount
    db.commit()
    if not claimed:
        return True
    db.refresh(job)
    try:
        result = HANDLERS[job.type](db, job)
    except Exception as exc:  # noqa: BLE001 - recorded on the job
        db.rollback()
        log.exception("job %s (%s) failed", job.id, job.type)
        job = db.get(Job, job.id)
        job.status, job.last_error = "failed", str(exc)[:1000]
        if job.type in ON_FAILURE:
            ON_FAILURE[job.type](db, job)
    else:
        job.status, job.result = "done", result
    job.finished_at = clock.now()
    db.commit()
    return True
