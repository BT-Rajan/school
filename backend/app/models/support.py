from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class SupportSession(Base):
    """An admin's read-only view of one user's screens (FR-AD3): with a reason, for at most
    30 minutes, every view audited, and shown to the user at their next sign-in."""

    __tablename__ = "support_sessions"
    __table_args__ = (Index("ix_support_sessions_user_shown", "user_id", "shown_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    started_at: Mapped[datetime] = mapped_column(default=clock.now)
    expires_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    views: Mapped[int] = mapped_column(default=0)
    shown_at: Mapped[datetime | None]
