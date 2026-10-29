from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class PushSubscription(Base):
    """One browser's permission to receive Web Push for one signed-in session (FR-N3).

    Tied to the session, so signing out on a shared phone stops that phone's pushes.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    # The endpoint is a long URL; its hash keeps one row per browser.
    endpoint_hash: Mapped[str] = mapped_column(String(64), unique=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class PushMessage(Base):
    """A notice waiting to be pushed; the worker sends it to each of the user's browsers."""

    __tablename__ = "push_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    sent_at: Mapped[datetime | None]
