from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class UploadSession(Base):
    """A resumable upload from a phone (FR-D6, FR-PW5).

    The phone sends the file in pieces and can resume after losing its connection.
    Pieces are sealed with this upload's own key as they arrive, like every stored file.
    The client key makes a replayed upload return the same file, never a second one.
    """

    __tablename__ = "upload_sessions"
    __table_args__ = (UniqueConstraint("user_id", "client_key", name="uq_upload_sessions_client_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int]
    received: Mapped[int] = mapped_column(default=0)
    wrapped_key: Mapped[str] = mapped_column(String(255))
    # Storage keys of the sealed pieces, in order.
    chunks: Mapped[list[Any]] = mapped_column(default=list)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("stored_files.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    completed_at: Mapped[datetime | None]
