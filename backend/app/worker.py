"""The single background worker: mail, digests, audit verification, housekeeping."""

import logging
import signal
import time
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, jobs
from app.audit import service as audit
from app.auth import rate_limit
from app.db import session_factory
from app.district import get_district, local_time_utc
from app.documents import service as documents
from app.errors import AppError
from app.files import resumable
from app.files import service as files
from app.mail import queue as mail
from app.models import Job
from app.push import service as push
from app.requests import service as requests
from app.scoring import service as scoring  # noqa: F401 - registers its job handlers

log = logging.getLogger(__name__)

MAIL_INTERVAL_SECONDS = 2
HOUSEKEEPING_INTERVAL_SECONDS = 60


def _run_daily(db: Session, name: str, at_hhmm: str, task: Callable[[Session], object]) -> bool:
    """Run a task once per district-local day, after the given local time."""
    district = get_district(db)
    today = clock.local_date(district.time_zone)
    if clock.now() < local_time_utc(district, today, at_hhmm):
        return False
    job_type = f"daily:{name}"
    done = db.execute(select(Job.id).where(Job.type == job_type, Job.payload["day"] == today.isoformat())).first()
    if done:
        return False
    job = Job(type=job_type, payload={"day": today.isoformat()}, status="running", attempts=1)
    db.add(job)
    db.commit()
    try:
        task(db)
    except Exception as exc:  # noqa: BLE001 - recorded and retried tomorrow
        db.rollback()
        job.status = "failed"
        job.last_error = str(exc)[:1000]
        log.exception("daily task %s failed", name)
    else:
        job.status = "done"
    job.finished_at = clock.now()
    db.commit()
    return True


def housekeeping(db: Session) -> None:
    district = get_district(db)
    mail.recover_stuck(db)
    _run_daily(db, "audit_verify", district.setting("audit_verify_time"), audit.run_verification)
    # Before the digest, so the reminder joins that day's email.
    _run_daily(db, "reports_overdue", "07:00", documents.remind_overdue)
    _run_daily(db, "request_reminders", "07:00", requests.remind)
    _run_daily(db, "digest", district.setting("digest_time"), mail.build_digests)
    _run_daily(db, "prune_rate_limits", "03:00", lambda s: rate_limit.prune(s, timedelta(days=2)))
    _run_daily(db, "prune_uploads", "03:00", resumable.prune)


def run_forever() -> None:
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_housekeeping = 0.0
    log.info("worker started")
    while not stopping:
        try:
            with session_factory()() as db:
                mail.dispatch(db)
                files.scan_pending(db)
                push.dispatch(db)
                jobs.run_next(db)
                if time.monotonic() - last_housekeeping > HOUSEKEEPING_INTERVAL_SECONDS:
                    housekeeping(db)
                    last_housekeeping = time.monotonic()
        except AppError as exc:
            log.warning("worker waiting: %s", exc.code)
        except Exception:  # noqa: BLE001 - keep the worker alive
            log.exception("worker cycle failed")
        time.sleep(MAIL_INTERVAL_SECONDS)
    log.info("worker stopped")
