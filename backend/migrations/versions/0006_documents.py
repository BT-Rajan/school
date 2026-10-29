"""Scanned report vault: documents, versions and forwards (section 9).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_supervisor_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=True),
        sa.Column("evaluation_id", sa.Integer(), nullable=True),
        sa.Column("ministry_report_version_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("first_viewed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("first_viewed_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("returned_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("returned_by", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("deleted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("retention_until", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], name=op.f("fk_documents_acknowledged_by_users")),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], name=op.f("fk_documents_cluster_id_clusters")),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name=op.f("fk_documents_deleted_by_users")),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["evaluations.id"], name=op.f("fk_documents_evaluation_id_evaluations")
        ),
        sa.ForeignKeyConstraint(["first_viewed_by"], ["users.id"], name=op.f("fk_documents_first_viewed_by_users")),
        sa.ForeignKeyConstraint(
            ["ministry_report_version_id"],
            ["ministry_report_versions.id"],
            name=op.f("fk_documents_ministry_report_version_id_ministry_report_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_supervisor_id"], ["supervisors.id"], name=op.f("fk_documents_owner_supervisor_id_supervisors")
        ),
        sa.ForeignKeyConstraint(["returned_by"], ["users.id"], name=op.f("fk_documents_returned_by_users")),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], name=op.f("fk_documents_school_id_schools")),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name=op.f("fk_documents_teacher_id_teachers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_cluster_id"), "documents", ["cluster_id"], unique=False)
    op.create_index(op.f("ix_documents_evaluation_id"), "documents", ["evaluation_id"], unique=False)
    op.create_index(
        "ix_documents_owner_status_date", "documents", ["owner_supervisor_id", "status", "report_date"], unique=False
    )
    op.create_index(
        "ix_documents_school_report", "documents", ["school_id", "ministry_report_version_id"], unique=False
    )
    op.create_index("ix_documents_status_submitted", "documents", ["status", "submitted_at"], unique=False)
    op.create_table(
        "document_forwards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("forwarded_by", sa.Integer(), nullable=False),
        sa.Column("forwarded_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], name=op.f("fk_document_forwards_cluster_id_clusters")),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_document_forwards_document_id_documents")
        ),
        sa.ForeignKeyConstraint(["forwarded_by"], ["users.id"], name=op.f("fk_document_forwards_forwarded_by_users")),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], name=op.f("fk_document_forwards_revoked_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_forwards")),
    )
    op.create_index(op.f("ix_document_forwards_document_id"), "document_forwards", ["document_id"], unique=False)
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("stored_file_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("client_key", sa.String(length=64), nullable=True),
        sa.Column("device_time", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_document_versions_created_by_users")),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_document_versions_document_id_documents")
        ),
        sa.ForeignKeyConstraint(
            ["stored_file_id"], ["stored_files.id"], name=op.f("fk_document_versions_stored_file_id_stored_files")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "client_key", name="uq_document_versions_client_key"),
    )
    op.create_index(op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False)
    # documents and document_versions refer to each other, so this key is added once both exist.
    op.create_foreign_key(
        op.f("fk_documents_current_version_id_document_versions"),
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_documents_current_version_id_document_versions"), "documents", type_="foreignkey")
    op.drop_table("document_versions")
    op.drop_table("document_forwards")
    op.drop_table("documents")
