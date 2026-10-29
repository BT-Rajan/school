"""Stored files: encrypted uploads with scan status (FR-FS1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("scan_status", sa.String(length=16), nullable=False),
        sa.Column("scan_detail", sa.String(length=255), nullable=True),
        sa.Column("scan_attempts", sa.Integer(), nullable=False),
        sa.Column("scan_after", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("scanned_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("wrapped_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("deleted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name=op.f("fk_stored_files_uploaded_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stored_files")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_stored_files_storage_key")),
    )
    op.create_index(op.f("ix_stored_files_scan_status"), "stored_files", ["scan_status"], unique=False)
    op.create_index(op.f("ix_stored_files_sha256"), "stored_files", ["sha256"], unique=False)
    op.create_index(op.f("ix_stored_files_uploaded_by"), "stored_files", ["uploaded_by"], unique=False)


def downgrade() -> None:
    op.drop_table("stored_files")
