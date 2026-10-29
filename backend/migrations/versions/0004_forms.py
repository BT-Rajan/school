"""Ministry report catalog, form versions and review comments (FR-MR1, FR-F2, FR-PB1).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ministry_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_code", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_ministry_reports_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ministry_reports")),
        sa.UniqueConstraint("report_code", name=op.f("uq_ministry_reports_report_code")),
    )
    op.create_table(
        "ministry_report_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ministry_report_id", sa.Integer(), nullable=False),
        sa.Column("version_code", sa.String(length=64), nullable=False),
        sa.Column("title_en", sa.String(length=300), nullable=False),
        sa.Column("title_ar", sa.String(length=300), nullable=False),
        sa.Column("ministry_published_on", sa.Date(), nullable=True),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_ministry_report_versions_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["ministry_report_id"],
            ["ministry_reports.id"],
            name=op.f("fk_ministry_report_versions_ministry_report_id_ministry_reports"),
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["stored_files.id"],
            name=op.f("fk_ministry_report_versions_source_file_id_stored_files"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ministry_report_versions")),
        sa.UniqueConstraint("ministry_report_id", "version_code", name="uq_ministry_report_versions_code"),
    )
    op.create_index(
        op.f("ix_ministry_report_versions_ministry_report_id"),
        "ministry_report_versions",
        ["ministry_report_id"],
        unique=False,
    )
    op.create_table(
        "form_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ministry_report_version_id", sa.Integer(), nullable=False),
        sa.Column("schema", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("built_by", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("published_by", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("closed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("close_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["built_by"], ["users.id"], name=op.f("fk_form_versions_built_by_users")),
        sa.ForeignKeyConstraint(
            ["ministry_report_version_id"],
            ["ministry_report_versions.id"],
            name=op.f("fk_form_versions_ministry_report_version_id_ministry_report_versions"),
        ),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"], name=op.f("fk_form_versions_published_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_versions")),
        sa.UniqueConstraint("ministry_report_version_id", name=op.f("uq_form_versions_ministry_report_version_id")),
    )
    op.create_index(op.f("ix_form_versions_status"), "form_versions", ["status"], unique=False)
    op.create_table(
        "form_review_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_version_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name=op.f("fk_form_review_comments_author_id_users")),
        sa.ForeignKeyConstraint(
            ["form_version_id"],
            ["form_versions.id"],
            name=op.f("fk_form_review_comments_form_version_id_form_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_review_comments")),
    )
    op.create_index(
        op.f("ix_form_review_comments_form_version_id"), "form_review_comments", ["form_version_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_form_review_comments_form_version_id"), table_name="form_review_comments")
    op.drop_table("form_review_comments")
    op.drop_index(op.f("ix_form_versions_status"), table_name="form_versions")
    op.drop_table("form_versions")
    op.drop_index(op.f("ix_ministry_report_versions_ministry_report_id"), table_name="ministry_report_versions")
    op.drop_table("ministry_report_versions")
    op.drop_table("ministry_reports")
