"""Read-only support views of a user's screens (FR-AD3).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("started_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("expires_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("ended_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("shown_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], name=op.f("fk_support_sessions_admin_id_users")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_support_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_sessions")),
    )
    op.create_index(op.f("ix_support_sessions_admin_id"), "support_sessions", ["admin_id"], unique=False)
    op.create_index("ix_support_sessions_user_shown", "support_sessions", ["user_id", "shown_at"], unique=False)


def downgrade() -> None:
    op.drop_table("support_sessions")
