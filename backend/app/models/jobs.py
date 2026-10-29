from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class Job(Base):
    """Database-backed job queue, run by the single worker process."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    run_after: Mapped[datetime] = mapped_column(default=clock.now, index=True)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    # Who asked for it, and what it produced (an export's file, a count), for jobs people start.
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    result: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class ImportBatch(Base):
    """A previewed CSV or Excel import, committed in a second step (FR-S4, FR-T2)."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("clusters.id"))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="previewed")
    rows: Mapped[list[Any]] = mapped_column(default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    committed_at: Mapped[datetime | None]
