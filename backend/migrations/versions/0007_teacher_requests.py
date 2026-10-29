"""Teacher requests: teacher sections of evaluations and standalone requests (section 8.6).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teacher_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("form_version_id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=True),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("via_contact", sa.Boolean(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=True),
        sa.Column("pending_teacher_id", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("returned_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("return_comment", sa.Text(), nullable=True),
        sa.Column("return_count", sa.Integer(), nullable=False),
        sa.Column("closed_by", sa.Integer(), nullable=True),
        sa.Column("closed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("close_reason", sa.String(length=1000), nullable=True),
        sa.Column("reminders", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], name=op.f("fk_teacher_requests_closed_by_users")),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["evaluations.id"], name=op.f("fk_teacher_requests_evaluation_id_evaluations")
        ),
        sa.ForeignKeyConstraint(
            ["form_version_id"], ["form_versions.id"], name=op.f("fk_teacher_requests_form_version_id_form_versions")
        ),
        sa.ForeignKeyConstraint(
            ["pending_teacher_id"], ["teachers.id"], name=op.f("fk_teacher_requests_pending_teacher_id_teachers")
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_teacher_requests_requested_by_users")),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], name=op.f("fk_teacher_requests_school_id_schools")),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name=op.f("fk_teacher_requests_teacher_id_teachers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teacher_requests")),
        sa.UniqueConstraint("evaluation_id", name=op.f("uq_teacher_requests_evaluation_id")),
    )
    op.create_index(op.f("ix_teacher_requests_form_version_id"), "teacher_requests", ["form_version_id"], unique=False)
    op.create_index(op.f("ix_teacher_requests_requested_by"), "teacher_requests", ["requested_by"], unique=False)
    op.create_index("ix_teacher_requests_school_status", "teacher_requests", ["school_id", "status"], unique=False)
    op.create_index("ix_teacher_requests_teacher_status", "teacher_requests", ["teacher_id", "status"], unique=False)
    op.add_column(
        "ministry_reports",
        sa.Column("standalone_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("ministry_reports", "standalone_allowed")
    op.drop_table("teacher_requests")
