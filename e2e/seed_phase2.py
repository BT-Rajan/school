"""Seed a fresh development database for the Phase 2 browser test (e2e/phase2.cjs).

Creates the district, one cluster with two schools, a District Admin, a Form Author,
a Cluster Head and two supervisors, all with authenticator apps, and prints their
emails and TOTP secrets as JSON. Never run it against production: it refuses to.

Usage, from backend/ with the app's environment set and migrations applied:
  PYTHONPATH=. .venv/bin/python ../e2e/seed_phase2.py > seed.json
"""

import json

import pyotp

from app.audit import service as audit
from app.config import get_settings
from app.db import session_factory
from app.models import Cluster, District, MfaMethod, Role, School, Supervisor, User, UserStatus
from app.models.district import DEFAULT_SETTINGS
from app.security import crypto, passwords
from app.structure.common import fold_search

PASSWORD = "a long e2e test passphrase"


def main() -> None:
    if get_settings().environment == "production":
        raise SystemExit("Refusing to seed a production database.")
    out: dict = {"password": PASSWORD, "users": {}}
    with session_factory()() as db:
        db.add(
            District(
                code="KW-E2E",
                name_en="E2E District",
                name_ar="منطقة الاختبار",
                time_zone="Asia/Kuwait",
                settings=dict(DEFAULT_SETTINGS),
            )
        )
        audit.ensure_head(db)
        db.flush()

        def user(key: str, role: Role, name: str, staff_id: str | None) -> User:
            secret = pyotp.random_base32()
            u = User(
                role=role,
                email=f"{key}@e2e.example.org",
                name=name,
                name_search=fold_search(name),
                staff_id=staff_id,
                status=UserStatus.ACTIVE,
                password_hash=passwords.hash_password(PASSWORD),
                mfa_method=MfaMethod.TOTP,
            )
            db.add(u)
            db.flush()
            u.totp_secret_enc = crypto.encrypt(secret, context=f"totp:{u.id}")
            out["users"][key] = {"email": u.email, "secret": secret, "name": name}
            return u

        user("admin", Role.DISTRICT_ADMIN, "Mariam Al-Ali", "A-1")
        user("author", Role.FORM_AUTHOR, "Omar Haddad", None)
        head = user("head", Role.CLUSTER_HEAD, "Khalid Al-Mutairi", "CH-1")
        sup_a = user("supa", Role.SUPERVISOR, "Noura Al-Saleh", "S-1")
        sup_b = user("supb", Role.SUPERVISOR, "Yousef Al-Kandari", "S-2")
        cluster = Cluster(code="C-01", name="Salmiya Cluster", cluster_head_id=head.id)
        db.add(cluster)
        db.flush()
        for code, name in (("SCH-1", "Al-Nahda Primary"), ("SCH-2", "مدرسة الفردوس")):
            db.add(
                School(
                    cluster_id=cluster.id,
                    code=code,
                    name=name,
                    name_search=fold_search(name),
                    address="Street 1",
                    school_type="primary",
                    medium="arabic",
                    contact_phone="+96500000000",
                )
            )
        for u in (sup_a, sup_b):
            db.add(Supervisor(user_id=u.id, cluster_id=cluster.id))
        db.commit()
    print(json.dumps(out))


if __name__ == "__main__":
    main()
