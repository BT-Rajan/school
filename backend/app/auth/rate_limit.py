"""Persistent rate limits for authentication actions (FR-A4).

Counts live in the database so they survive restarts. The caller commits.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import clock
from app.errors import AppError
from app.models import RateLimitEvent


def hit(db: Session, key: str, limit: int, window: timedelta) -> bool:
    """Record an attempt. Returns False, without recording, when over the limit."""
    since = clock.now() - window
    count = db.execute(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(RateLimitEvent.key == key, RateLimitEvent.created_at > since)
    ).scalar_one()
    if count >= limit:
        return False
    db.add(RateLimitEvent(key=key, created_at=clock.now()))
    db.flush()
    return True


def require(db: Session, key: str, limit: int, window: timedelta) -> None:
    if not hit(db, key, limit, window):
        db.commit()
        raise AppError(429, "rate_limited", headers={"Retry-After": str(int(window.total_seconds()))})


def prune(db: Session, older_than: timedelta = timedelta(days=2)) -> None:
    db.execute(delete(RateLimitEvent).where(RateLimitEvent.created_at < clock.now() - older_than))
    db.commit()


class SlidingWindow:
    """In-process limiter for general API traffic (section 15). One API process in v1."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


api_limiter = SlidingWindow()
