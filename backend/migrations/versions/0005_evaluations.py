"""Evaluations, their sections and amendments (FR-E1 to FR-E9).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_version_id", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=True),
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=True),
        sa.Column("visit_notes", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("location_accuracy_m", sa.Integer(), nullable=True),
        sa.Column("client_key", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("amended_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("score", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["form_version_id"], ["form_versions.id"], name=op.f("fk_evaluations_form_version_id_form_versions")
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], name=op.f("fk_evaluations_school_id_schools")),
        sa.ForeignKeyConstraint(
            ["supervisor_id"], ["supervisors.id"], name=op.f("fk_evaluations_supervisor_id_supervisors")
        ),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name=op.f("fk_evaluations_teacher_id_teachers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluations")),
        sa.UniqueConstraint("supervisor_id", "client_key", name="uq_evaluations_client_key"),
    )
    op.create_index(op.f("ix_evaluations_form_version_id"), "evaluations", ["form_version_id"], unique=False)
    op.create_index("ix_evaluations_school_status", "evaluations", ["school_id", "status"], unique=False)
    op.create_index("ix_evaluations_supervisor_status", "evaluations", ["supervisor_id", "status"], unique=False)
    op.create_index(op.f("ix_evaluations_teacher_id"), "evaluations", ["teacher_id"], unique=False)
    op.create_table(
        "evaluation_amendments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("prior", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_evaluation_amendments_created_by_users")),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["evaluations.id"], name=op.f("fk_evaluation_amendments_evaluation_id_evaluations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_amendments")),
    )
    op.create_index(
        op.f("ix_evaluation_amendments_evaluation_id"), "evaluation_amendments", ["evaluation_id"], unique=False
    )
    op.create_table(
        "evaluation_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("section_key", sa.String(length=64), nullable=False),
        sa.Column("respondent", sa.String(length=16), nullable=False),
        sa.Column("respondent_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["evaluations.id"], name=op.f("fk_evaluation_sections_evaluation_id_evaluations")
        ),
        sa.ForeignKeyConstraint(
            ["respondent_user_id"], ["users.id"], name=op.f("fk_evaluation_sections_respondent_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_sections")),
        sa.UniqueConstraint("evaluation_id", "section_key", name="uq_evaluation_sections_key"),
    )
    op.create_index(
        op.f("ix_evaluation_sections_respondent_user_id"), "evaluation_sections", ["respondent_user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("evaluation_sections")
    op.drop_table("evaluation_amendments")
    op.drop_table("evaluations")
