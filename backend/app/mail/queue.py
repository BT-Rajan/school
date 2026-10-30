"""Mail queue with priorities and a daily budget (FR-N5, FR-N6, FR-N8).

Budget rules, per district-local day, for a daily limit L and reserve r:
- Security mail may be sent while fewer than L messages went out today.
- All other mail stops once floor(L * (1 - r)) general messages went out, so
  at least L * r messages are always left for sign-in and reset codes.
- Mail over budget waits for the next day. Nothing is dropped.
"""

import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app import clock
from app.district import get_district, local_midnight_utc, local_time_utc
from app.mail.providers import MailProvider, OutgoingMail, get_provider
from app.mail.templates import render
from app.models import (
    BudgetClass,
    District,
    MailDailyUsage,
    MailMessage,
    MailPriority,
    MailStatus,
    Role,
    User,
    UserStatus,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
ALERT_FRACTION = 0.8


def enqueue(
    db: Session,
    template: str,
    *,
    recipient: str,
    locale: str,
    context: dict[str, Any] | None = None,
    priority: MailPriority,
    user_id: int | None = None,
    digest: bool = False,
    scheduled_for=None,
) -> MailMessage:
    budget = BudgetClass.RESERVED if priority == MailPriority.SECURITY else BudgetClass.GENERAL
    message = MailMessage(
        template=template,
        locale=locale,
        recipient=recipient,
        user_id=user_id,
        context=context or {},
        priority=int(priority),
        budget_class=budget,
        digest=digest and priority >= MailPriority.REMINDER,
        status=MailStatus.DIGEST_PENDING if digest and priority >= MailPriority.REMINDER else MailStatus.QUEUED,
        scheduled_for=scheduled_for or clock.now(),
    )
    db.add(message)
    db.flush()
    return message


def send_to_user(
    db: Session, user: User, template: str, context: dict[str, Any], priority: MailPriority, **kwargs: Any
) -> MailMessage:
    return enqueue(
        db,
        template,
        recipient=user.email,
        locale=user.locale,
        context=context,
        priority=priority,
        user_id=user.id,
        **kwargs,
    )


def alert_admins(db: Session, template: str, context: dict[str, Any]) -> None:
    admins = db.execute(
        select(User).where(User.role == Role.DISTRICT_ADMIN, User.status == UserStatus.ACTIVE)
    ).scalars()
    for admin in admins:
        send_to_user(db, admin, template, context, MailPriority.SECURITY)


def _caps(district: District) -> tuple[int, int]:
    limit = int(district.setting("mail_daily_limit"))
    general_cap = math.floor(limit * (1 - float(district.setting("mail_reserve_fraction"))))
    return limit, general_cap


def _lock_usage(db: Session, day: date) -> MailDailyUsage:
    db.execute(mysql_insert(MailDailyUsage).values(day=day, sent_total=0, sent_general=0).prefix_with("IGNORE"))
    return db.execute(select(MailDailyUsage).where(MailDailyUsage.day == day).with_for_update()).scalar_one()


def _claim_next(db: Session, district: District) -> tuple[MailMessage | None, bool]:
    """Claim the next sendable message. Returns (message, budget_exhausted)."""
    usage = _lock_usage(db, clock.local_date(district.time_zone))
    limit, general_cap = _caps(district)
    if usage.sent_total >= limit:
        db.commit()
        return None, True
    query = (
        select(MailMessage)
        .where(MailMessage.status == MailStatus.QUEUED, MailMessage.scheduled_for <= clock.now())
        .order_by(MailMessage.priority, MailMessage.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if usage.sent_general >= general_cap:
        query = query.where(MailMessage.budget_class == BudgetClass.RESERVED)
    message = db.execute(query).scalar_one_or_none()
    if message is None:
        db.commit()
        return None, usage.sent_general >= general_cap
    message.status = MailStatus.SENDING
    message.attempts += 1
    usage.sent_total += 1
    if message.budget_class == BudgetClass.GENERAL:
        usage.sent_general += 1
    if not usage.alerted and usage.sent_total >= limit * ALERT_FRACTION:
        usage.alerted = True
        alert_admins(
            db,
            "mail_quota_warning",
            {"percent": round(100 * usage.sent_total / limit), "sent": usage.sent_total, "limit": limit},
        )
    db.commit()
    return message, False


def dispatch(db: Session, provider: MailProvider | None = None, max_messages: int = 100) -> int:
    """Send due messages in priority order within today's budget. Returns the count sent."""
    provider = provider or get_provider()
    district = get_district(db)
    sent = 0
    for _ in range(max_messages):
        message, _exhausted = _claim_next(db, district)
        if message is None:
            break
        rendered = render(message.template, message.locale, message.context or {})
        try:
            sender = get_district(db).setting("mail_sender_name") or None
            provider_id = provider.send(
                OutgoingMail(message.recipient, rendered.subject, rendered.text, rendered.html, sender_name=sender)
            )
        except Exception as exc:  # noqa: BLE001 - any provider failure is retried
            log.warning("mail %s failed: %s", message.id, exc)
            message.error = str(exc)[:500]
            if message.attempts >= MAX_ATTEMPTS:
                message.status = MailStatus.FAILED
                message.context = None
            else:
                message.status = MailStatus.QUEUED
                message.scheduled_for = clock.now() + timedelta(minutes=2**message.attempts)
            db.commit()
            continue
        message.status = MailStatus.SENT
        message.sent_at = clock.now()
        message.provider_message_id = provider_id
        message.error = None
        message.context = None
        db.commit()
        sent += 1
    return sent


def recover_stuck(db: Session, older_than_minutes: int = 10) -> None:
    """Return messages left in 'sending' by a crashed process to the queue."""
    cutoff = clock.now() - timedelta(minutes=older_than_minutes)
    stuck = db.execute(
        select(MailMessage).where(MailMessage.status == MailStatus.SENDING, MailMessage.scheduled_for < cutoff)
    ).scalars()
    for message in stuck:
        message.status = MailStatus.QUEUED
    db.commit()


def invitation_send_times(db: Session, count: int) -> list:
    """Spread invitations over days within the daily invitation cap (FR-N8)."""
    district = get_district(db)
    cap = int(district.setting("invitation_daily_cap"))
    today = clock.local_date(district.time_zone)
    horizon = local_midnight_utc(district, today)
    scheduled = db.execute(
        select(MailMessage.scheduled_for).where(
            MailMessage.priority == MailPriority.INVITATION,
            MailMessage.status.in_([MailStatus.QUEUED, MailStatus.SENT, MailStatus.SENDING]),
            MailMessage.scheduled_for >= horizon,
        )
    ).scalars()
    per_day: dict[date, int] = defaultdict(int)
    for at in scheduled:
        per_day[clock.local_date(district.time_zone, at)] += 1
    times = []
    day = today
    while len(times) < count:
        free = cap - per_day[day]
        if free > 0:
            start = clock.now() if day == today else local_midnight_utc(district, day)
            take = min(free, count - len(times))
            times.extend([start] * take)
            per_day[day] += take
        day += timedelta(days=1)
    return times


def build_digests(db: Session) -> int:
    """Combine each recipient's pending reminders and notices into one message."""
    pending = (
        db.execute(
            select(MailMessage)
            .where(MailMessage.status == MailStatus.DIGEST_PENDING)
            .order_by(MailMessage.recipient, MailMessage.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )
    grouped: dict[tuple[str, str, int | None], list[MailMessage]] = defaultdict(list)
    for message in pending:
        grouped[(message.recipient, message.locale, message.user_id)].append(message)
    for (recipient, locale, user_id), messages in grouped.items():
        priority = min(m.priority for m in messages)
        enqueue(
            db,
            "digest",
            recipient=recipient,
            locale=locale,
            user_id=user_id,
            priority=MailPriority(priority),
            context={"items": [{"template": m.template, "context": m.context} for m in messages]},
        )
        for message in messages:
            message.status = MailStatus.DIGESTED
            message.context = None
    db.commit()
    return len(grouped)


def digest_due_at(district: District, day: date):
    return local_time_utc(district, day, district.setting("digest_time"))


def usage_today(db: Session) -> dict[str, int]:
    district = get_district(db)
    usage = db.get(MailDailyUsage, clock.local_date(district.time_zone))
    limit, general_cap = _caps(district)
    queued = db.execute(
        select(func.count()).select_from(MailMessage).where(MailMessage.status == MailStatus.QUEUED)
    ).scalar_one()
    return {
        "limit": limit,
        "general_cap": general_cap,
        "sent_total": usage.sent_total if usage else 0,
        "sent_general": usage.sent_general if usage else 0,
        "queued": queued,
    }
