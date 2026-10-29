import json
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from app import clock
from app.config import get_settings
from app.mail import queue as mail
from app.mail.providers import ConsoleProvider, GmailApiProvider, OutgoingMail
from app.models import District, MailMessage, MailPriority, MailStatus, Role

from .helpers import make_user


def _set(db, **settings):
    district = db.execute(select(District)).scalar_one()
    district.settings = {**district.settings, **settings}
    db.commit()


def _queue(db, n, priority, template="digest", **kwargs):
    for i in range(n):
        mail.enqueue(
            db,
            template,
            recipient=f"user{i}@example.org",
            locale="en",
            context={"items": []},
            priority=priority,
            **kwargs,
        )
    db.commit()


def test_security_mail_goes_first(db):
    provider = ConsoleProvider()
    _queue(db, 3, MailPriority.INFORMATIONAL)
    mail.enqueue(
        db,
        "login_code",
        recipient="urgent@example.org",
        locale="en",
        context={"code": "123456"},
        priority=MailPriority.SECURITY,
    )
    db.commit()
    mail.dispatch(db, provider, max_messages=1)
    assert provider.outbox[0].to == "urgent@example.org"


def test_reserve_keeps_room_for_login_codes(db):
    """With the general budget used up, a login code still goes out and a reminder waits."""
    _set(db, mail_daily_limit=10, mail_reserve_fraction=0.4)
    provider = ConsoleProvider()
    _queue(db, 8, MailPriority.REMINDER)
    assert mail.dispatch(db, provider) == 6  # floor(10 * 0.6)
    mail.enqueue(
        db,
        "login_code",
        recipient="t@example.org",
        locale="en",
        context={"code": "111111"},
        priority=MailPriority.SECURITY,
    )
    db.commit()
    assert mail.dispatch(db, provider) == 1
    waiting = db.execute(select(MailMessage).where(MailMessage.status == MailStatus.QUEUED)).scalars().all()
    assert len(waiting) == 2
    # The next district-local day, the waiting reminders are sent. Nothing was dropped.
    clock.freeze(clock.now() + timedelta(days=1))
    assert mail.dispatch(db, provider) == 2


def test_total_limit_stops_everything(db):
    _set(db, mail_daily_limit=4, mail_reserve_fraction=0.5)
    provider = ConsoleProvider()
    for i in range(6):
        mail.enqueue(
            db,
            "login_code",
            recipient=f"u{i}@example.org",
            locale="en",
            context={"code": "1"},
            priority=MailPriority.SECURITY,
        )
    db.commit()
    assert mail.dispatch(db, provider) == 4


def test_quota_alert_at_80_percent(db):
    make_user(Role.DISTRICT_ADMIN, "admin@example.org")
    _set(db, mail_daily_limit=10, mail_reserve_fraction=0.0)
    provider = ConsoleProvider()
    _queue(db, 8, MailPriority.INFORMATIONAL)
    mail.dispatch(db, provider)
    assert any(m.to == "admin@example.org" and "quota" in m.subject.lower() for m in provider.outbox)


def test_failed_send_is_retried_with_backoff(db):
    class Flaky:
        def __init__(self):
            self.calls = 0

        def send(self, message):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary")
            return "ok-1"

    provider = Flaky()
    mail.enqueue(
        db, "login_code", recipient="t@example.org", locale="en", context={"code": "1"}, priority=MailPriority.SECURITY
    )
    db.commit()
    assert mail.dispatch(db, provider) == 0
    message = db.execute(select(MailMessage)).scalar_one()
    assert message.status == MailStatus.QUEUED and message.error == "temporary"
    clock.freeze(clock.now() + timedelta(minutes=3))
    assert mail.dispatch(db, provider) == 1
    db.refresh(message)
    assert message.status == MailStatus.SENT and message.provider_message_id == "ok-1" and message.context is None


def test_invitations_spread_over_days(db):
    """212 invitations with a cap of 150 a day go out over two days."""
    times = mail.invitation_send_times(db, 212)
    district = db.execute(select(District)).scalar_one()
    days = {}
    for at in times:
        day = clock.local_date(district.time_zone, at)
        days[day] = days.get(day, 0) + 1
    assert sorted(days.values(), reverse=True) == [150, 62]


def test_digest_combines_messages_per_recipient(db):
    provider = ConsoleProvider()
    for template in ("mfa_reset_notice", "mfa_reset_notice"):
        mail.enqueue(
            db,
            template,
            recipient="t@example.org",
            locale="en",
            context={},
            priority=MailPriority.REMINDER,
            digest=True,
        )
    mail.enqueue(
        db,
        "mfa_reset_notice",
        recipient="u@example.org",
        locale="ar",
        context={},
        priority=MailPriority.INFORMATIONAL,
        digest=True,
    )
    db.commit()
    assert mail.dispatch(db, provider) == 0  # nothing sent until the digest is built
    assert mail.build_digests(db) == 2
    mail.dispatch(db, provider)
    assert sorted(m.to for m in provider.outbox) == ["t@example.org", "u@example.org"]
    english = next(m for m in provider.outbox if m.to == "t@example.org")
    assert english.subject == "Your daily summary" and english.text.count("- ") == 2


def test_gmail_provider_refreshes_token_and_sends():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok"
        assert "raw" in json.loads(request.content)
        return httpx.Response(200, json={"id": "gmail-123"})

    provider = GmailApiProvider(get_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    message = OutgoingMail("t@example.org", "Subject", "Body", "<p>Body</p>")
    assert provider.send(message) == "gmail-123"
    assert provider.send(message) == "gmail-123"
    # The access token is reused while valid.
    assert sum(1 for r in requests if r.url.host == "oauth2.googleapis.com") == 1


def test_district_day_boundary_uses_time_zone(db):
    # 21:30 UTC is already the next day in Kuwait (UTC+3).
    assert clock.local_date("Asia/Kuwait", datetime(2026, 11, 5, 21, 30)).day == 6
