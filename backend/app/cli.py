"""Server-side commands: python -m app.cli <command>."""

import argparse
import sys

from sqlalchemy import select

from app.audit import service as audit
from app.auth import service as auth
from app.config import get_settings
from app.db import session_factory
from app.logging_setup import configure_logging
from app.models import District, Role
from app.models.district import DEFAULT_SETTINGS
from app.security import crypto, tokens
from app.structure import people


def bootstrap(args) -> None:
    with session_factory()() as db:
        if db.execute(select(District)).first():
            print("District already configured.")
            return
        db.add(
            District(
                code=args.code,
                name_en=args.name_en,
                name_ar=args.name_ar,
                time_zone=args.time_zone,
                default_locale="en",
                date_format="D/MM/YYYY",
                settings=dict(DEFAULT_SETTINGS),
            )
        )
        audit.ensure_head(db)
        db.flush()
        audit.record(
            db,
            "district.bootstrapped",
            entity_type="district",
            actor_role="server_cli",
            after={"code": args.code, "time_zone": args.time_zone},
        )
        db.commit()
        print(f"District {args.code} created.")


def _create(role: Role, args) -> None:
    with session_factory()() as db:
        user = people.create_user(
            db,
            role=role,
            name=args.name,
            email=args.email,
            staff_id=getattr(args, "staff_id", None),
            locale=args.locale,
            created_by=None,
        )
        # Printed as well as emailed, since mail may not be set up yet on a new server.
        token = auth.create_invitation(db, user, None)
        db.commit()
        print(f"Invitation for {user.email}: {get_settings().public_base_url}/invite/{token}")


def break_glass(args) -> None:
    if not args.yes:
        typed = input(f"Type the email address again to reset {args.email}: ")
        if typed.strip().lower() != args.email.strip().lower():
            print("Cancelled.")
            sys.exit(1)
    with session_factory()() as db:
        seq = auth.break_glass_reset(db, args.email)
    print(f"Second factor reset. Audit entry {seq}. All other admins have been emailed.")


def verify_audit(_args) -> None:
    with session_factory()() as db:
        result = audit.run_verification(db)
    print(
        f"{'OK' if result.ok else 'BROKEN'}: {result.checked} entries checked"
        + (f", break at {result.broken_at_seq}: {result.detail}" if not result.ok else "")
    )
    sys.exit(0 if result.ok else 2)


def generate_keys(_args) -> None:
    print(f"SCES_SECRET_KEY={tokens.new_token()}{tokens.new_token()}")
    print(f"SCES_ENCRYPTION_KEY={crypto.generate_key()}")
    from app.push.service import generate_vapid_keys

    public, private = generate_vapid_keys()
    print(f"SCES_VAPID_PUBLIC_KEY={public}")
    print(f"SCES_VAPID_PRIVATE_KEY={private}")


def grants_sql(args) -> None:
    """Print GRANT statements for the application database user (FR-L3).

    The app user may read and write every table except audit_log, where it
    may only SELECT and INSERT. Run again after each migration that adds tables.
    """
    from app.db import Base

    user = f"'{args.user}'@'{args.host}'"
    for line in app_grants(Base.metadata.sorted_tables, args.database, user):
        print(line)


def app_grants(tables, database: str, user: str) -> list[str]:
    lines = []
    for table in tables:
        privileges = "SELECT, INSERT" if table.name == "audit_log" else "SELECT, INSERT, UPDATE, DELETE"
        lines.append(f"GRANT {privileges} ON `{database}`.`{table.name}` TO {user};")
    lines.append(f"GRANT SELECT ON `{database}`.`alembic_version` TO {user};")
    return lines


def provision_database(args) -> None:
    """Migrate, then create the restricted application user and its grants.

    Runs with the privileged SCES_MIGRATION_DATABASE_URL. The application user's
    password comes from SCES_APP_DB_PASSWORD. Safe to run on every deploy.
    """
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, make_url, text

    from app.db import Base

    admin_url = os.environ.get("SCES_MIGRATION_DATABASE_URL")
    password = os.environ.get("SCES_APP_DB_PASSWORD")
    if not admin_url or not password:
        sys.exit("Set SCES_MIGRATION_DATABASE_URL and SCES_APP_DB_PASSWORD")
    backend = Path(__file__).resolve().parent.parent
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(config, "head")

    database = make_url(admin_url).database
    user = f"'{args.user}'@'{args.host}'"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f"CREATE USER IF NOT EXISTS {user} IDENTIFIED BY :pw"), {"pw": password})
        conn.execute(text(f"ALTER USER {user} IDENTIFIED BY :pw"), {"pw": password})
        for statement in app_grants(Base.metadata.sorted_tables, database, user):
            conn.execute(text(statement))
    engine.dispose()
    print(f"Database {database} migrated; {user} provisioned.")


def verify_files(args) -> None:
    """Decrypt stored files and compare each with its recorded SHA-256 (FR-D56, restore test)."""
    import random

    from app.files.service import read_content
    from app.models.files import StoredFile

    with session_factory()() as db:
        ids = list(db.execute(select(StoredFile.id).where(StoredFile.deleted_at.is_(None))).scalars())
        sample = ids if args.sample <= 0 or args.sample >= len(ids) else random.sample(ids, args.sample)
        failures = []
        for file_id in sample:
            try:
                read_content(db.get(StoredFile, file_id))
            except Exception as exc:  # noqa: BLE001 - every failure is reported
                failures.append(f"{file_id}: {type(exc).__name__}")
    print(f"{len(sample) - len(failures)} of {len(sample)} files verified")
    for line in failures:
        print(f"FAILED {line}")
    sys.exit(1 if failures else 0)


def worker(_args) -> None:
    from app.worker import run_forever

    run_forever()


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("bootstrap", help="Create the district record")
    p.add_argument("--code", required=True)
    p.add_argument("--name-en", required=True)
    p.add_argument("--name-ar", required=True)
    p.add_argument("--time-zone", required=True, help="IANA name, for example Asia/Kuwait")
    p.set_defaults(func=bootstrap)

    p = commands.add_parser("create-admin", help="Invite a District Admin")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--staff-id", required=True)
    p.add_argument("--locale", default="en", choices=["en", "ar"])
    p.set_defaults(func=lambda a: _create(Role.DISTRICT_ADMIN, a))

    p = commands.add_parser("create-form-author", help="Invite an implementation-team Form Author")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--locale", default="en", choices=["en", "ar"])
    p.set_defaults(func=lambda a: _create(Role.FORM_AUTHOR, a))

    p = commands.add_parser("break-glass-reset", help="Emergency reset of a user's second factor")
    p.add_argument("--email", required=True)
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    p.set_defaults(func=break_glass)

    commands.add_parser("verify-audit", help="Recompute the audit hash chain").set_defaults(func=verify_audit)
    commands.add_parser("generate-keys", help="Print new secret keys").set_defaults(func=generate_keys)
    commands.add_parser("worker", help="Run the background worker").set_defaults(func=worker)

    p = commands.add_parser("grants-sql", help="Print GRANT statements for the application database user")
    p.add_argument("--database", required=True)
    p.add_argument("--user", default="sces_app")
    p.add_argument("--host", default="%")
    p.set_defaults(func=grants_sql)

    p = commands.add_parser("verify-files", help="Check stored files against their checksums")
    p.add_argument("--sample", type=int, default=0, help="Number of random files to check; 0 checks all")
    p.set_defaults(func=verify_files)

    p = commands.add_parser("provision-database", help="Migrate and provision the application database user")
    p.add_argument("--user", default="sces_app")
    p.add_argument("--host", default="%")
    p.set_defaults(func=provision_database)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
