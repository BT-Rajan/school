"""Web Push subscriptions and outbox (FR-N3).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("sent_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_push_messages_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_messages")),
    )
    op.create_index(op.f("ix_push_messages_status"), "push_messages", ["status"], unique=False)
    op.create_index(op.f("ix_push_messages_user_id"), "push_messages", ["user_id"], unique=False)
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_push_subscriptions_session_id_sessions")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_push_subscriptions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
        sa.UniqueConstraint("endpoint_hash", name=op.f("uq_push_subscriptions_endpoint_hash")),
    )
    op.create_index(op.f("ix_push_subscriptions_session_id"), "push_subscriptions", ["session_id"], unique=False)
    op.create_index(op.f("ix_push_subscriptions_user_id"), "push_subscriptions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("push_subscriptions")
    op.drop_table("push_messages")
