"""Tests run against a real MySQL 8 server.

Set TEST_MYSQL_ROOT_URL to a server where the test user may create a
database, for example mysql+pymysql://root:root@127.0.0.1:3306. The schema is
built with the real migrations, and the app connects as a restricted user,
exactly as in production.
"""

import os
from urllib.parse import urlsplit

ROOT_URL = os.environ.get("TEST_MYSQL_ROOT_URL", "mysql+pymysql://root:root@127.0.0.1:3306")
DB_NAME = os.environ.get("TEST_MYSQL_DATABASE", "sces_test")
_host = urlsplit(ROOT_URL).netloc.split("@")[-1]
APP_URL = f"mysql+pymysql://sces_app_test:sces_app_test@{_host}/{DB_NAME}?charset=utf8mb4"

os.environ.update(
    {
        "SCES_ENVIRONMENT": "test",
        "SCES_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters",
        "SCES_ENCRYPTION_KEY": "k0Z2oPq8n3wJ4cXy7Vb1Lm9Rt5Hs6Gf2Ad8Ek3Uw4Yz",
        "SCES_DATABASE_URL": APP_URL,
        "SCES_MIGRATION_DATABASE_URL": f"{ROOT_URL}/{DB_NAME}?charset=utf8mb4",
        "SCES_COOKIE_SECURE": "false",
        "SCES_PUBLIC_BASE_URL": "https://sces.test",
        "SCES_MAIL_PROVIDER": "console",
    }
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app import clock  # noqa: E402
from app.auth.rate_limit import api_limiter  # noqa: E402
from app.cli import app_grants  # noqa: E402
from app.db import Base, reset_engine, session_factory  # noqa: E402
from app.mail import providers  # noqa: E402
from app.models import District  # noqa: E402
from app.models.district import DEFAULT_SETTINGS  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def root_engine():
    server = create_engine(ROOT_URL, isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{DB_NAME}`"))
        conn.execute(text(f"CREATE DATABASE `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
        conn.execute(text("DROP USER IF EXISTS 'sces_app_test'@'%'"))
        conn.execute(text("CREATE USER 'sces_app_test'@'%' IDENTIFIED BY 'sces_app_test'"))
    config = Config(os.path.join(BACKEND, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND, "migrations"))
    command.upgrade(config, "head")
    with server.connect() as conn:
        for statement in app_grants(Base.metadata.sorted_tables, DB_NAME, "'sces_app_test'@'%'"):
            conn.execute(text(statement))
    engine = create_engine(f"{ROOT_URL}/{DB_NAME}?charset=utf8mb4")
    yield engine
    engine.dispose()
    server.dispose()


@pytest.fixture(autouse=True)
def clean_database(root_engine):
    with root_engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in Base.metadata.sorted_tables:
            if table.name != "audit_chain_head":
                conn.execute(text(f"DELETE FROM `{table.name}`"))
        conn.execute(text("UPDATE audit_chain_head SET last_seq = 0, last_hash = :h"), {"h": "0" * 64})
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    reset_engine()
    with session_factory()() as db:
        db.add(
            District(
                code="KW-01",
                name_en="Test District",
                name_ar="المنطقة التجريبية",
                time_zone="Asia/Kuwait",
                settings=dict(DEFAULT_SETTINGS),
            )
        )
        db.commit()
    api_limiter.reset()
    clock.freeze(None)
    yield
    clock.freeze(None)


@pytest.fixture
def outbox():
    provider = providers.ConsoleProvider()
    providers.set_provider(provider)
    yield provider.outbox
    providers.set_provider(None)


@pytest.fixture
def db():
    with session_factory()() as session:
        yield session


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app, outbox):
    return TestClient(app)


@pytest.fixture
def new_client(app, outbox):
    """Factory for extra independent browsers (separate cookie jars)."""
    return lambda: TestClient(app)
