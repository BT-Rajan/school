"""Read-only support view of a user's screens (FR-AD3).

A District Admin starts a support session for one user, with a reason, for at most 30
minutes. While it lasts, the admin's requests that carry the session's id are answered as that
user would see them, and only reads are allowed: nothing can be changed, submitted, uploaded
or downloaded through it (file links are created by POST, which is refused). Every view is
audited against the admin, and the user is shown the session at their next sign-in.
"""

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.db import session_factory
from app.errors import AppError, not_found
from app.models import Role, SupportSession, User, UserStatus
from app.structure.common import like_pattern

MAX_MINUTES = 30


class StartIn(BaseModel):
    user_id: int
    reason: str = Field(min_length=10, max_length=1000)
    minutes: int = Field(default=MAX_MINUTES, ge=5, le=MAX_MINUTES)


def session_out(db: Session, s: SupportSession) -> dict[str, Any]:
    user = db.get(User, s.user_id)
    return {
        "id": s.id,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
        "admin": db.get(User, s.admin_id).name,
        "reason": s.reason,
        "started_at": s.started_at,
        "expires_at": s.expires_at,
        "ended_at": s.ended_at,
        "active": is_active(s),
        "views": s.views,
    }


def is_active(s: SupportSession) -> bool:
    return s.ended_at is None and s.expires_at > clock.now()


def find_users(db: Session, q: str) -> list[dict[str, Any]]:
    """Accounts an admin may view: anyone but another admin."""
    term = q.strip()
    if len(term) < 2:
        return []
    rows = db.execute(
        select(User)
        .where(
            User.role != Role.DISTRICT_ADMIN,
            User.status != UserStatus.INVITED,
            or_(User.name_search.like(like_pattern(term)), User.email.like(f"%{term}%"), User.staff_id == term),
        )
        .order_by(User.name)
        .limit(20)
    ).scalars()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "staff_id": u.staff_id} for u in rows]


def start(db: Session, admin: User, body: StartIn) -> SupportSession:
    user = db.get(User, body.user_id)
    if user is None:
        raise not_found()
    if user.role == Role.DISTRICT_ADMIN:
        # An admin's screens hold nothing another admin cannot already see as themselves.
        raise AppError(409, "support_not_for_admins")
    # One at a time: starting a new view ends the admin's earlier one.
    for open_ in db.execute(
        select(SupportSession).where(SupportSession.admin_id == admin.id, SupportSession.ended_at.is_(None))
    ).scalars():
        open_.ended_at = clock.now()
    s = SupportSession(
        admin_id=admin.id,
        user_id=user.id,
        reason=body.reason,
        started_at=clock.now(),
        expires_at=clock.now() + timedelta(minutes=body.minutes),
    )
    db.add(s)
    db.flush()
    audit.record(
        db,
        "support.started",
        entity_type="user",
        entity_id=user.id,
        severity="warning",
        after={"support_session_id": s.id, "reason": body.reason, "minutes": body.minutes},
    )
    db.commit()
    return s


def end(db: Session, admin: User, session_id: int) -> SupportSession:
    s = db.get(SupportSession, session_id)
    if s is None or s.admin_id != admin.id:
        raise not_found()
    if s.ended_at is None:
        s.ended_at = min(clock.now(), s.expires_at)
        audit.record(
            db,
            "support.ended",
            entity_type="user",
            entity_id=s.user_id,
            after={"support_session_id": s.id, "views": s.views},
        )
        db.commit()
    return s


def mine(db: Session, admin: User) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SupportSession).where(SupportSession.admin_id == admin.id).order_by(SupportSession.id.desc()).limit(20)
    ).scalars()
    return [session_out(db, s) for s in rows]


def resolve(db: Session, admin: User, raw_id: str, method: str, path: str) -> User:
    """The user an admin's request is answered as, for a support session header."""
    if admin.role != Role.DISTRICT_ADMIN or not raw_id.isdigit():
        raise AppError(403, "support_session_invalid")
    s = db.get(SupportSession, int(raw_id))
    if s is None or s.admin_id != admin.id or not is_active(s):
        raise AppError(403, "support_session_invalid")
    if method not in ("GET", "HEAD"):
        audit.record_denial(
            f"{method} {path[:200]}", entity_type="user", entity_id=s.user_id, reason="support_read_only", request_db=db
        )
        raise AppError(403, "support_read_only")
    user = db.get(User, s.user_id)
    # Every view is recorded at once, in its own transaction, whatever the request does next.
    with session_factory()() as own:
        row = own.get(SupportSession, s.id)
        row.views += 1
        audit.record(
            own,
            "support.viewed",
            entity_type="user",
            entity_id=user.id,
            actor_id=admin.id,
            actor_role=admin.role,
            after={"support_session_id": s.id, "path": path[:300]},
        )
        own.commit()
    return user


def notices(db: Session, user: User) -> list[dict[str, Any]]:
    """Support views of this user's screens not yet shown to them (FR-AD3)."""
    rows = db.execute(
        select(SupportSession).where(SupportSession.user_id == user.id, SupportSession.shown_at.is_(None))
    ).scalars()
    return [
        {
            "id": s.id,
            "admin": db.get(User, s.admin_id).name,
            "reason": s.reason,
            "started_at": s.started_at,
            "ended_at": s.ended_at or s.expires_at,
        }
        for s in rows
        if not is_active(s)
    ]


def mark_shown(db: Session, user: User) -> None:
    for s in db.execute(
        select(SupportSession).where(SupportSession.user_id == user.id, SupportSession.shown_at.is_(None))
    ).scalars():
        if not is_active(s):
            s.shown_at = clock.now()
    db.commit()
