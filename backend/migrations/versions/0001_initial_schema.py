"""Initial schema: accounts, authentication, audit, mail, jobs, district structure.

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_head",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_chain_head")),
    )
    # The audit chain starts from an all-zero hash (app.audit.service.GENESIS_HASH).
    op.bulk_insert(
        sa.table("audit_chain_head", sa.column("id"), sa.column("last_seq"), sa.column("last_hash")),
        [{"id": 1, "last_seq": 0, "last_hash": "0" * 64}],
    )
    op.create_table(
        "audit_log",
        sa.Column("seq", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_actor_id"), "audit_log", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_log_cluster_id"), "audit_log", ["cluster_id"], unique=False)
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"], unique=False)
    op.create_table(
        "audit_verifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ran_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("checked_count", sa.Integer(), nullable=False),
        sa.Column("broken_at_seq", sa.BigInteger(), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_verifications")),
    )
    op.create_table(
        "custom_field_definitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("field_type", sa.String(length=16), nullable=False),
        sa.Column("label_en", sa.String(length=200), nullable=False),
        sa.Column("label_ar", sa.String(length=200), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_field_definitions")),
        sa.UniqueConstraint("entity", "key", name="uq_custom_field_definitions_entity_key"),
    )
    op.create_table(
        "districts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name_en", sa.String(length=200), nullable=False),
        sa.Column("name_ar", sa.String(length=200), nullable=False),
        sa.Column("default_locale", sa.String(length=8), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("date_format", sa.String(length=16), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_districts")),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("finished_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_run_after"), "jobs", ["run_after"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_type"), "jobs", ["type"], unique=False)
    op.create_table(
        "mail_daily_usage",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("sent_total", sa.Integer(), nullable=False),
        sa.Column("sent_general", sa.Integer(), nullable=False),
        sa.Column("alerted", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_mail_daily_usage")),
    )
    op.create_table(
        "mail_queue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("recipient", sa.String(length=254), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("budget_class", sa.String(length=16), nullable=False),
        sa.Column("digest", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scheduled_for", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("sent_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_queue")),
    )
    op.create_index(op.f("ix_mail_queue_priority"), "mail_queue", ["priority"], unique=False)
    op.create_index(op.f("ix_mail_queue_recipient"), "mail_queue", ["recipient"], unique=False)
    op.create_index(op.f("ix_mail_queue_scheduled_for"), "mail_queue", ["scheduled_for"], unique=False)
    op.create_index(op.f("ix_mail_queue_status"), "mail_queue", ["status"], unique=False)
    op.create_index(op.f("ix_mail_queue_user_id"), "mail_queue", ["user_id"], unique=False)
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_limit_events")),
    )
    op.create_index(op.f("ix_rate_limit_events_created_at"), "rate_limit_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_rate_limit_events_key"), "rate_limit_events", ["key"], unique=False)
    op.create_table(
        "reference_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("list_name", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_en", sa.String(length=200), nullable=False),
        sa.Column("name_ar", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_values")),
        sa.UniqueConstraint("list_name", "code", name="uq_reference_values_list_code"),
    )
    op.create_index(op.f("ix_reference_values_list_name"), "reference_values", ["list_name"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("email_verified_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("staff_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_search", sa.String(length=200), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("mfa_method", sa.String(length=16), nullable=False),
        sa.Column("totp_secret_enc", sa.String(length=255), nullable=True),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column("failed_code_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("last_login_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("staff_id", name=op.f("uq_users_staff_id")),
    )
    op.create_index(op.f("ix_users_name_search"), "users", ["name_search"], unique=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_table(
        "auth_challenges",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("pending_secret_enc", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("used_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_auth_challenges_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_challenges")),
    )
    op.create_index(op.f("ix_auth_challenges_user_id"), "auth_challenges", ["user_id"], unique=False)
    op.create_table(
        "clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("cluster_head_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_head_id"], ["users.id"], name=op.f("fk_clusters_cluster_head_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clusters")),
        sa.UniqueConstraint("code", name=op.f("uq_clusters_code")),
    )
    op.create_index(op.f("ix_clusters_cluster_head_id"), "clusters", ["cluster_head_id"], unique=False)
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("used_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_invitations_created_by_users")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_invitations_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(op.f("ix_invitations_user_id"), "invitations", ["user_id"], unique=False)
    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_recovery_codes_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_recovery_codes_code_hash")),
    )
    op.create_index(op.f("ix_recovery_codes_user_id"), "recovery_codes", ["user_id"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("committed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], name=op.f("fk_import_batches_cluster_id_clusters")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_import_batches_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batches")),
    )
    op.create_table(
        "schools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_search", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("school_type", sa.String(length=64), nullable=False),
        sa.Column("medium", sa.String(length=64), nullable=False),
        sa.Column("contact_phone", sa.String(length=32), nullable=False),
        sa.Column("contact_email", sa.String(length=254), nullable=True),
        sa.Column("custom", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], name=op.f("fk_schools_cluster_id_clusters")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schools")),
        sa.UniqueConstraint("code", name=op.f("uq_schools_code")),
    )
    op.create_index(op.f("ix_schools_cluster_id"), "schools", ["cluster_id"], unique=False)
    op.create_index(op.f("ix_schools_name_search"), "schools", ["name_search"], unique=False)
    op.create_index(op.f("ix_schools_status"), "schools", ["status"], unique=False)
    op.create_table(
        "supervisors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], name=op.f("fk_supervisors_cluster_id_clusters")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_supervisors_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supervisors")),
        sa.UniqueConstraint("user_id", name=op.f("uq_supervisors_user_id")),
    )
    op.create_index(op.f("ix_supervisors_cluster_id"), "supervisors", ["cluster_id"], unique=False)
    op.create_index(op.f("ix_supervisors_status"), "supervisors", ["status"], unique=False)
    op.create_table(
        "supervisor_cluster_moves",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("from_cluster_id", sa.Integer(), nullable=False),
        sa.Column("to_cluster_id", sa.Integer(), nullable=False),
        sa.Column("moved_by", sa.Integer(), nullable=False),
        sa.Column("moved_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_cluster_id"], ["clusters.id"], name=op.f("fk_supervisor_cluster_moves_from_cluster_id_clusters")
        ),
        sa.ForeignKeyConstraint(["moved_by"], ["users.id"], name=op.f("fk_supervisor_cluster_moves_moved_by_users")),
        sa.ForeignKeyConstraint(
            ["supervisor_id"], ["supervisors.id"], name=op.f("fk_supervisor_cluster_moves_supervisor_id_supervisors")
        ),
        sa.ForeignKeyConstraint(
            ["to_cluster_id"], ["clusters.id"], name=op.f("fk_supervisor_cluster_moves_to_cluster_id_clusters")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supervisor_cluster_moves")),
    )
    op.create_index(
        op.f("ix_supervisor_cluster_moves_supervisor_id"), "supervisor_cluster_moves", ["supervisor_id"], unique=False
    )
    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("designation_id", sa.Integer(), nullable=False),
        sa.Column("experience_years", sa.Integer(), nullable=False),
        sa.Column("experience_as_of", sa.Date(), nullable=False),
        sa.Column("custom", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["designation_id"], ["reference_values.id"], name=op.f("fk_teachers_designation_id_reference_values")
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], name=op.f("fk_teachers_school_id_schools")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_teachers_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teachers")),
        sa.UniqueConstraint("user_id", name=op.f("uq_teachers_user_id")),
    )
    op.create_index(op.f("ix_teachers_school_id"), "teachers", ["school_id"], unique=False)
    op.create_index(op.f("ix_teachers_status"), "teachers", ["status"], unique=False)
    op.create_table(
        "school_contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_school_contacts_created_by_users")),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], name=op.f("fk_school_contacts_school_id_schools")),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name=op.f("fk_school_contacts_teacher_id_teachers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_school_contacts")),
    )
    op.create_index(op.f("ix_school_contacts_school_id"), "school_contacts", ["school_id"], unique=False)
    op.create_index(op.f("ix_school_contacts_teacher_id"), "school_contacts", ["teacher_id"], unique=False)
    op.create_table(
        "teacher_classes",
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("reference_value_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reference_value_id"],
            ["reference_values.id"],
            name=op.f("fk_teacher_classes_reference_value_id_reference_values"),
        ),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name=op.f("fk_teacher_classes_teacher_id_teachers")),
        sa.PrimaryKeyConstraint("teacher_id", "reference_value_id", name=op.f("pk_teacher_classes")),
    )
    op.create_table(
        "teacher_qualifications",
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("reference_value_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["reference_value_id"],
            ["reference_values.id"],
            name=op.f("fk_teacher_qualifications_reference_value_id_reference_values"),
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teachers.id"], name=op.f("fk_teacher_qualifications_teacher_id_teachers")
        ),
        sa.PrimaryKeyConstraint("teacher_id", "reference_value_id", name=op.f("pk_teacher_qualifications")),
    )
    op.create_table(
        "teacher_subjects",
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("reference_value_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reference_value_id"],
            ["reference_values.id"],
            name=op.f("fk_teacher_subjects_reference_value_id_reference_values"),
        ),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name=op.f("fk_teacher_subjects_teacher_id_teachers")),
        sa.PrimaryKeyConstraint("teacher_id", "reference_value_id", name=op.f("pk_teacher_subjects")),
    )
    op.create_table(
        "teacher_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("from_school_id", sa.Integer(), nullable=False),
        sa.Column("to_school_id", sa.Integer(), nullable=False),
        sa.Column("moved_on", sa.Date(), nullable=False),
        sa.Column("moved_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_school_id"], ["schools.id"], name=op.f("fk_teacher_transfers_from_school_id_schools")
        ),
        sa.ForeignKeyConstraint(["moved_by"], ["users.id"], name=op.f("fk_teacher_transfers_moved_by_users")),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], name=op.f("fk_teacher_transfers_teacher_id_teachers")),
        sa.ForeignKeyConstraint(
            ["to_school_id"], ["schools.id"], name=op.f("fk_teacher_transfers_to_school_id_schools")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teacher_transfers")),
    )
    op.create_index(op.f("ix_teacher_transfers_teacher_id"), "teacher_transfers", ["teacher_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_teacher_transfers_teacher_id"), table_name="teacher_transfers")
    op.drop_table("teacher_transfers")
    op.drop_table("teacher_subjects")
    op.drop_table("teacher_qualifications")
    op.drop_table("teacher_classes")
    op.drop_index(op.f("ix_school_contacts_teacher_id"), table_name="school_contacts")
    op.drop_index(op.f("ix_school_contacts_school_id"), table_name="school_contacts")
    op.drop_table("school_contacts")
    op.drop_index(op.f("ix_teachers_status"), table_name="teachers")
    op.drop_index(op.f("ix_teachers_school_id"), table_name="teachers")
    op.drop_table("teachers")
    op.drop_index(op.f("ix_supervisor_cluster_moves_supervisor_id"), table_name="supervisor_cluster_moves")
    op.drop_table("supervisor_cluster_moves")
    op.drop_index(op.f("ix_supervisors_status"), table_name="supervisors")
    op.drop_index(op.f("ix_supervisors_cluster_id"), table_name="supervisors")
    op.drop_table("supervisors")
    op.drop_index(op.f("ix_schools_status"), table_name="schools")
    op.drop_index(op.f("ix_schools_name_search"), table_name="schools")
    op.drop_index(op.f("ix_schools_cluster_id"), table_name="schools")
    op.drop_table("schools")
    op.drop_table("import_batches")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_recovery_codes_user_id"), table_name="recovery_codes")
    op.drop_table("recovery_codes")
    op.drop_index(op.f("ix_invitations_user_id"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_index(op.f("ix_clusters_cluster_head_id"), table_name="clusters")
    op.drop_table("clusters")
    op.drop_index(op.f("ix_auth_challenges_user_id"), table_name="auth_challenges")
    op.drop_table("auth_challenges")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_name_search"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_reference_values_list_name"), table_name="reference_values")
    op.drop_table("reference_values")
    op.drop_index(op.f("ix_rate_limit_events_key"), table_name="rate_limit_events")
    op.drop_index(op.f("ix_rate_limit_events_created_at"), table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
    op.drop_index(op.f("ix_mail_queue_user_id"), table_name="mail_queue")
    op.drop_index(op.f("ix_mail_queue_status"), table_name="mail_queue")
    op.drop_index(op.f("ix_mail_queue_scheduled_for"), table_name="mail_queue")
    op.drop_index(op.f("ix_mail_queue_recipient"), table_name="mail_queue")
    op.drop_index(op.f("ix_mail_queue_priority"), table_name="mail_queue")
    op.drop_table("mail_queue")
    op.drop_table("mail_daily_usage")
    op.drop_index(op.f("ix_jobs_type"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_run_after"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("districts")
    op.drop_table("custom_field_definitions")
    op.drop_table("audit_verifications")
    op.drop_index(op.f("ix_audit_log_created_at"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_cluster_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("audit_chain_head")
