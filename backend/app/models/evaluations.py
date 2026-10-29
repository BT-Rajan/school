from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class Evaluation(Base):
    """A School or Teacher evaluation by one supervisor, on one form version (FR-E1 to FR-E9)."""

    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_supervisor_status", "supervisor_id", "status"),
        Index("ix_evaluations_school_status", "school_id", "status"),
        # Offline submissions carry a client key, so a replay never creates a duplicate (FR-PW5).
        UniqueConstraint("supervisor_id", "client_key", name="uq_evaluations_client_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_versions.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(16))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"), index=True)
    supervisor_id: Mapped[int] = mapped_column(ForeignKey("supervisors.id"))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    visit_date: Mapped[date | None]
    visit_notes: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    location_accuracy_m: Mapped[int | None]
    client_key: Mapped[str | None] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None]
    amended_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    # Score results arrive with the district's formula (FR-SC2); score fields are already in the answers.
    score: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}


class EvaluationSection(Base):
    __tablename__ = "evaluation_sections"
    __table_args__ = (UniqueConstraint("evaluation_id", "section_key", name="uq_evaluation_sections_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id"))
    section_key: Mapped[str] = mapped_column(String(64))
    respondent: Mapped[str] = mapped_column(String(16))
    respondent_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="not_started")
    answers: Mapped[dict[str, Any]] = mapped_column(default=dict)
    submitted_at: Mapped[datetime | None]


class EvaluationAmendment(Base):
    """A correction to a submitted evaluation, keeping what it replaced (FR-E7)."""

    __tablename__ = "evaluation_amendments"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id"), index=True)
    reason: Mapped[str] = mapped_column(String(1000))
    prior: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
