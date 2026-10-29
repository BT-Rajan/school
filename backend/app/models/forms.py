from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class MinistryReport(Base):
    """A report the ministry publishes, identified by its ministry report ID (FR-MR1)."""

    __tablename__ = "ministry_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_code: Mapped[str] = mapped_column(String(64), unique=True)
    subject_type: Mapped[str] = mapped_column(String(16))  # school or teacher
    # Approved by a District Admin for standalone teacher requests (FR-R1).
    standalone_allowed: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class MinistryReportVersion(Base):
    """One ministry revision of a report. Each version gets its own form (FR-MR2, FR-MR4)."""

    __tablename__ = "ministry_report_versions"
    __table_args__ = (UniqueConstraint("ministry_report_id", "version_code", name="uq_ministry_report_versions_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ministry_report_id: Mapped[int] = mapped_column(ForeignKey("ministry_reports.id"), index=True)
    version_code: Mapped[str] = mapped_column(String(64))
    title_en: Mapped[str] = mapped_column(String(300))
    title_ar: Mapped[str] = mapped_column(String(300))
    ministry_published_on: Mapped[date | None]
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("stored_files.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class FormVersion(Base):
    """The form built for one ministry report version (FR-F2, FR-F10).

    Stored status is draft, in_review or published. Scheduled, active and closed
    are derived from the dates, so a form opens and closes on time with no job.
    """

    __tablename__ = "form_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ministry_report_version_id: Mapped[int] = mapped_column(ForeignKey("ministry_report_versions.id"), unique=True)
    schema: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    built_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None]
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}

    def effective_status(self, today: date) -> str:
        if self.status != "published":
            return self.status
        if self.closed_at is not None or (self.end_date is not None and today > self.end_date):
            return "closed"
        if self.start_date is not None and today < self.start_date:
            return "scheduled"
        return "active"


class FormReviewComment(Base):
    __tablename__ = "form_review_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_versions.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))  # returned, submitted, published, extended, closed
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
