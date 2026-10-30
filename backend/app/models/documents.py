from datetime import date, datetime
from typing import Any

from sqlalchemy import Computed, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base

REVIEW_PRIORITY = "status in ('submitted', 'viewed', 'returned', 'draft')"


class Document(Base):
    """One scanned report, owned by the supervisor who uploaded it (section 9).

    Statuses: draft, submitted, viewed, acknowledged, returned, withdrawn.
    Deleted documents keep their status and get deleted_at (soft delete, FR-D30).
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_status_date", "owner_supervisor_id", "status", "report_date"),
        # The inbox: by status, or work waiting for review first, then newest. The trailing
        # columns let the list filter and count from the index alone (section 15).
        Index("ix_documents_status_submitted", "status", "submitted_at", "id", "archived_at", "deleted_at"),
        Index(
            "ix_documents_review_order", "review_priority", "submitted_at", "id", "archived_at", "deleted_at", "status"
        ),
        Index("ix_documents_school_report", "school_id", "ministry_report_version_id"),
        # Dashboard coverage: which schools have a submitted report for each report version.
        Index("ix_documents_report_coverage", "ministry_report_version_id", "school_id", "deleted_at", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_supervisor_id: Mapped[int] = mapped_column(ForeignKey("supervisors.id"))
    # The school's cluster when the report was made; forwarding and scope follow it.
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"), index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))
    evaluation_id: Mapped[int | None] = mapped_column(ForeignKey("evaluations.id"), index=True)
    ministry_report_version_id: Mapped[int] = mapped_column(ForeignKey("ministry_report_versions.id"))
    title: Mapped[str] = mapped_column(String(300))
    report_date: Mapped[date]
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # 1 for work not yet acknowledged; the inbox lists it first.
    review_priority: Mapped[int] = mapped_column(SmallInteger, Computed(REVIEW_PRIORITY, persisted=True))
    current_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id", use_alter=True))
    submitted_at: Mapped[datetime | None]
    first_viewed_at: Mapped[datetime | None]
    first_viewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None]
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_comment: Mapped[str | None] = mapped_column(Text)
    returned_at: Mapped[datetime | None]
    returned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    retention_until: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}


class DocumentVersion(Base):
    """Each replacement file is a new version; earlier ones are kept (FR-D23, FR-D24)."""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "client_key", name="uq_document_versions_client_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    version_no: Mapped[int]
    stored_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    reason: Mapped[str | None] = mapped_column(String(1000))
    client_key: Mapped[str | None] = mapped_column(String(64))
    device_time: Mapped[datetime | None]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class DocumentForward(Base):
    """View access for the Cluster Head of the document's cluster, given by an admin (FR-D25).

    Access follows the cluster's current Cluster Head, so a vacancy reassignment moves it.
    """

    __tablename__ = "document_forwards"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"))
    note: Mapped[str | None] = mapped_column(String(1000))
    forwarded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    forwarded_at: Mapped[datetime] = mapped_column(default=clock.now)
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
