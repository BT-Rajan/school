from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class StoredFile(Base):
    """One stored file (FR-FS1). The bytes live encrypted in the object store.

    owner_type and owner_id say which feature the file belongs to, and so which
    access rule applies. A fresh upload is owned by "upload" until a feature
    (an evaluation answer, a scanned report) takes it over.
    """

    __tablename__ = "stored_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Random identifier; never contains names, school IDs or titles (FR-D51).
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    owner_type: Mapped[str] = mapped_column(String(32), default="upload")
    owner_id: Mapped[int | None]
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    # SHA-256 of the stored (sanitized) content, before encryption (FR-D56).
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None]
    scan_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    scan_detail: Mapped[str | None] = mapped_column(String(255))
    scan_attempts: Mapped[int] = mapped_column(default=0)
    scan_after: Mapped[datetime] = mapped_column(default=clock.now)
    scanned_at: Mapped[datetime | None]
    # Per-file data key, wrapped with the master key (FR-D50).
    wrapped_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    deleted_at: Mapped[datetime | None]
