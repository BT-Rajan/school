from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class Notification(Base):
    """In-app notification center (FR-N1)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(64))
    # Identifiers and short labels only, never file content (FR-N7).
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=clock.now, index=True)


class NotificationPreference(Base):
    """A user's choice for an optional notification type on one channel (FR-N4)."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "type", "channel", name="uq_notification_preferences_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(default=True)
