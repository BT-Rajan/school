"""Resumable uploads (FR-D6).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("client_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("received", sa.Integer(), nullable=False),
        sa.Column("wrapped_key", sa.String(length=255), nullable=False),
        sa.Column("chunks", sa.JSON(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("completed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["stored_files.id"], name=op.f("fk_upload_sessions_file_id_stored_files")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_upload_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_sessions")),
        sa.UniqueConstraint("user_id", "client_key", name="uq_upload_sessions_client_key"),
    )


def downgrade() -> None:
    op.drop_table("upload_sessions")
