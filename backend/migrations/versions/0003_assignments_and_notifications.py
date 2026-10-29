"""Supervisor assignments and in-app notifications (FR-AS1, FR-N1).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notification_preferences_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint("user_id", "type", "channel", name="uq_notification_preferences_key"),
    )
    op.create_index(op.f("ix_notification_preferences_user_id"), "notification_preferences", ["user_id"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"], unique=False)
    op.create_table(
        "supervisor_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("end_reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("ended_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("ended_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_supervisor_assignments_created_by_users")),
        sa.ForeignKeyConstraint(["ended_by"], ["users.id"], name=op.f("fk_supervisor_assignments_ended_by_users")),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name=op.f("fk_supervisor_assignments_school_id_schools")
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_id"], ["supervisors.id"], name=op.f("fk_supervisor_assignments_supervisor_id_supervisors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supervisor_assignments")),
    )
    op.create_index(
        "ix_supervisor_assignments_school_dates",
        "supervisor_assignments",
        ["school_id", "start_date", "end_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supervisor_assignments_supervisor_id"), "supervisor_assignments", ["supervisor_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_supervisor_assignments_supervisor_id"), table_name="supervisor_assignments")
    op.drop_index("ix_supervisor_assignments_school_dates", table_name="supervisor_assignments")
    op.drop_table("supervisor_assignments")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_notification_preferences_user_id"), table_name="notification_preferences")
    op.drop_table("notification_preferences")
