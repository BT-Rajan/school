from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class TeacherRequest(Base):
    """What a teacher is asked to answer (FR-R1 to FR-R6).

    Either the teacher sections of an evaluation (kind "evaluation"), or a standalone
    request on a published form approved for that use (kind "standalone"). The teacher's
    answers live here, by section key, for both kinds.

    via_contact marks requests addressed to a school's contact teacher rather than to a
    person: they follow the contact role when it changes (FR-S6). teacher_id is empty while
    the school has no contact teacher. pending_teacher_id holds a new contact teacher who
    takes over a started request once the requester confirms (section 6.1).

    Statuses: not_started, in_progress, submitted, returned, waived, cancelled. Overdue is
    not stored: it is an open request whose due date has passed in district time.
    """

    __tablename__ = "teacher_requests"
    __table_args__ = (
        Index("ix_teacher_requests_teacher_status", "teacher_id", "status"),
        Index("ix_teacher_requests_school_status", "school_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_versions.id"), index=True)
    evaluation_id: Mapped[int | None] = mapped_column(ForeignKey("evaluations.id"), unique=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    via_contact: Mapped[bool] = mapped_column(default=False)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))
    pending_teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    due_date: Mapped[date]
    instructions: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="not_started")
    answers: Mapped[dict[str, Any]] = mapped_column(default=dict)
    submitted_at: Mapped[datetime | None]
    returned_at: Mapped[datetime | None]
    return_comment: Mapped[str | None] = mapped_column(Text)
    return_count: Mapped[int] = mapped_column(default=0)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[str | None] = mapped_column(String(1000))
    # Reminders already sent, so the daily run never repeats one (FR-R6).
    reminders: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}
