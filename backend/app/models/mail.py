from datetime import date, datetime
from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base
from app.models.enums import MailStatus


class MailMessage(Base):
    """Outbound mail queue and send log (FR-N5, FR-N6)."""

    __tablename__ = "mail_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    template: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(8))
    recipient: Mapped[str] = mapped_column(String(254), index=True)
    user_id: Mapped[int | None] = mapped_column(index=True)
    # Template values. Cleared after sending, since it can hold a login code.
    context: Mapped[dict[str, Any] | None]
    priority: Mapped[int] = mapped_column(index=True)
    budget_class: Mapped[str] = mapped_column(String(16))
    digest: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default=MailStatus.QUEUED, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(default=clock.now, index=True)
    sent_at: Mapped[datetime | None]
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class MailDailyUsage(Base):
    """Messages sent per district-local day, for the quota (FR-N8)."""

    __tablename__ = "mail_daily_usage"

    day: Mapped[date] = mapped_column(primary_key=True)
    sent_total: Mapped[int] = mapped_column(default=0)
    sent_general: Mapped[int] = mapped_column(default=0)
    alerted: Mapped[bool] = mapped_column(default=False)
