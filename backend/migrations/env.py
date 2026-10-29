"""Migrations run as a privileged database user (SCES_MIGRATION_DATABASE_URL).

The application itself connects as a restricted user that cannot UPDATE or
DELETE audit rows (FR-L3); see deploy/mysql/grants.sql.
"""

import os

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401 - registers every table
from app.db import Base

target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get("SCES_MIGRATION_DATABASE_URL") or os.environ.get("SCES_DATABASE_URL")
    if not url:
        raise RuntimeError("Set SCES_MIGRATION_DATABASE_URL to run migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
