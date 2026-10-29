"""Scoring rule sets and recorded recalculations (FR-SC2, FR-SC3); jobs people start.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "score_rule_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_version_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("activated_by", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("retired_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"], name=op.f("fk_score_rule_sets_activated_by_users")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_score_rule_sets_created_by_users")),
        sa.ForeignKeyConstraint(
            ["form_version_id"], ["form_versions.id"], name=op.f("fk_score_rule_sets_form_version_id_form_versions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_rule_sets")),
    )
    op.create_index("ix_score_rule_sets_form_status", "score_rule_sets", ["form_version_id", "status"], unique=False)
    op.create_table(
        "score_recalculations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_version_id", sa.Integer(), nullable=False),
        sa.Column("rule_set_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("evaluations", sa.Integer(), nullable=False),
        sa.Column("changed", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("finished_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(
            ["form_version_id"],
            ["form_versions.id"],
            name=op.f("fk_score_recalculations_form_version_id_form_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], name=op.f("fk_score_recalculations_requested_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_id"], ["score_rule_sets.id"], name=op.f("fk_score_recalculations_rule_set_id_score_rule_sets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_recalculations")),
    )
    op.create_index(
        op.f("ix_score_recalculations_form_version_id"), "score_recalculations", ["form_version_id"], unique=False
    )
    op.add_column("jobs", sa.Column("created_by", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("result", sa.JSON(), nullable=True))
    op.add_column(
        "jobs", sa.Column("started_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    )
    op.create_foreign_key(op.f("fk_jobs_created_by_users"), "jobs", "users", ["created_by"], ["id"])


def downgrade() -> None:
    op.drop_constraint(op.f("fk_jobs_created_by_users"), "jobs", type_="foreignkey")
    op.drop_column("jobs", "started_at")
    op.drop_column("jobs", "result")
    op.drop_column("jobs", "created_by")
    op.drop_table("score_recalculations")
    op.drop_table("score_rule_sets")
