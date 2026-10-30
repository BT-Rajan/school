"""The scanned report inbox, dashboards and record histories read from indexes (section 15).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

REVIEW_PRIORITY = "status in ('submitted', 'viewed', 'returned', 'draft')"


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("review_priority", sa.SmallInteger(), sa.Computed(REVIEW_PRIORITY, persisted=True), nullable=True),
    )
    op.drop_index("ix_documents_status_submitted", table_name="documents")
    op.create_index(
        "ix_documents_status_submitted", "documents", ["status", "submitted_at", "id", "archived_at", "deleted_at"]
    )
    op.create_index(
        "ix_documents_review_order",
        "documents",
        ["review_priority", "submitted_at", "id", "archived_at", "deleted_at", "status"],
    )
    op.create_index(
        "ix_documents_report_coverage",
        "documents",
        ["ministry_report_version_id", "school_id", "deleted_at", "status"],
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    # MySQL dropped the foreign key's own index once the coverage index could serve it.
    op.create_index(
        "fk_documents_ministry_report_version_id_ministry_report_versions",
        "documents",
        ["ministry_report_version_id"],
    )
    op.drop_index("ix_documents_report_coverage", table_name="documents")
    op.drop_index("ix_documents_review_order", table_name="documents")
    op.drop_index("ix_documents_status_submitted", table_name="documents")
    op.create_index("ix_documents_status_submitted", "documents", ["status", "submitted_at"])
    op.drop_column("documents", "review_priority")
