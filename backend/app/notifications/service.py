"""In-app notifications and their email copies (FR-N1, FR-N2, FR-N4, FR-N7).

Every notice goes to the in-app center at once. Its email copy joins the
user's daily digest, so routine notices never compete with sign-in codes
for the mail budget (FR-N8). Users can turn either channel off per type.
"""

from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import clock
from app.errors import invalid, not_found
from app.mail import queue as mail
from app.mail.templates import NOTICES, notice_text
from app.models import MailPriority, Notification, NotificationPreference, Role, School, Supervisor, User, UserStatus

CHANNELS = ("in_app", "email")


def _enabled(db: Session, user_id: int, type_: str, channel: str) -> bool:
    pref = db.execute(
        select(NotificationPreference.enabled).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.type == type_,
            NotificationPreference.channel == channel,
        )
    ).scalar_one_or_none()
    return True if pref is None else pref


def notify(db: Session, user_id: int, type_: str, payload: dict[str, Any]) -> None:
    if type_ not in NOTICES:
        raise ValueError(f"unknown notice type {type_}")
    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return
    payload = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in payload.items()}
    if _enabled(db, user.id, type_, "in_app"):
        db.add(Notification(user_id=user.id, type=type_, payload=payload, created_at=clock.now()))
    if _enabled(db, user.id, type_, "email"):
        mail.send_to_user(
            db, user, "notice", {"type": type_, "params": payload}, MailPriority.INFORMATIONAL, digest=True
        )
    db.flush()


def notify_role(db: Session, role: Role, type_: str, payload: dict[str, Any]) -> None:
    for user_id in db.execute(select(User.id).where(User.role == role, User.status == UserStatus.ACTIVE)).scalars():
        notify(db, user_id, type_, payload)


# Typed helpers used by features ---------------------------------------------------


def assignment_changed(db: Session, supervisor_id: int, type_: str, school: School, day: date | None) -> None:
    supervisor = db.get(Supervisor, supervisor_id)
    notify(db, supervisor.user_id, type_, {"school": school.name, "school_code": school.code, "date": day})


# Notification center ----------------------------------------------------------------


def notification_out(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "type": n.type,
        "payload": n.payload,
        # The same wording as the email, so the screen can switch language without a reload.
        "text": {locale: notice_text(n.type, locale, n.payload or {}) for locale in ("en", "ar")},
        "read": n.read_at is not None,
        "created_at": n.created_at,
    }


def list_for(db: Session, user_id: int, unread_only: bool = False, limit: int = 50) -> dict[str, Any]:
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    items = db.execute(query.order_by(Notification.id.desc()).limit(min(limit, 200))).scalars()
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ).scalar_one()
    return {"items": [notification_out(n) for n in items], "unread": unread}


def mark_read(db: Session, user_id: int, notification_id: int | None = None) -> None:
    query = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    if notification_id is not None:
        if db.get(Notification, notification_id) is None or db.get(Notification, notification_id).user_id != user_id:
            raise not_found()
        query = query.where(Notification.id == notification_id)
    db.execute(query.values(read_at=clock.now()))
    db.commit()


def preferences(db: Session, user_id: int) -> list[dict[str, Any]]:
    stored = {
        (p.type, p.channel): p.enabled
        for p in db.execute(select(NotificationPreference).where(NotificationPreference.user_id == user_id)).scalars()
    }
    return [{"type": t, **{c: stored.get((t, c), True) for c in CHANNELS}} for t in NOTICES]


def set_preference(db: Session, user_id: int, type_: str, channel: str, enabled: bool) -> None:
    if type_ not in NOTICES or channel not in CHANNELS:
        raise invalid("preference_unknown")
    pref = db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.type == type_,
            NotificationPreference.channel == channel,
        )
    ).scalar_one_or_none()
    if pref is None:
        db.add(NotificationPreference(user_id=user_id, type=type_, channel=channel, enabled=enabled))
    else:
        pref.enabled = enabled
    db.commit()
