"""Builders for test data. All tests share these; nothing is copied between tests."""

import re

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_factory
from app.mail import queue as mail
from app.mail.providers import get_provider
from app.models import Cluster, MfaMethod, ReferenceValue, Role, School, User, UserStatus
from app.security import crypto, passwords, totp
from app.structure.common import fold_search

PASSWORD = "correct horse battery staple"


def make_user(
    role: Role,
    email: str,
    *,
    name: str | None = None,
    staff_id: str | None = None,
    mfa: str = MfaMethod.EMAIL,
    status: str = UserStatus.ACTIVE,
) -> tuple[User, str | None]:
    """Create an account directly. Returns the user and, for TOTP users, the secret."""
    secret = pyotp.random_base32() if mfa == MfaMethod.TOTP else None
    with session_factory()() as db:
        user = User(
            role=role,
            email=email,
            name=name or email.split("@")[0],
            name_search=fold_search(name or email.split("@")[0]),
            staff_id=staff_id,
            status=status,
            password_hash=passwords.hash_password(PASSWORD),
            mfa_method=mfa,
        )
        db.add(user)
        db.flush()
        if secret:
            user.totp_secret_enc = crypto.encrypt(secret, context=f"totp:{user.id}")
        db.commit()
        db.refresh(user)
        return user, secret


def deliver_mail() -> None:
    with session_factory()() as db:
        mail.dispatch(db, get_provider())


def last_code(outbox, to: str) -> str:
    deliver_mail()
    for message in reversed(outbox):
        if message.to == to:
            found = re.search(r"\b(\d{6})\b", message.text)
            if found:
                return found.group(1)
    raise AssertionError(f"no code mailed to {to}")


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("sces_csrf", "")}


def login(client: TestClient, outbox, email: str, *, secret: str | None = None, password: str = PASSWORD) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    challenge = response.json()["challenge"]
    if secret:
        # The server's clock, which tests may freeze, decides which code is current.
        code = totp.code_at_step(secret, totp.current_step())
    else:
        code = last_code(outbox, email)
    response = client.post("/api/auth/login/verify", json={"challenge": challenge, "code": code})
    assert response.status_code == 200, response.text
    client.headers.update(csrf(client))
    return response.json()


def signed_in(new_client, outbox, role: Role, email: str, **kwargs) -> tuple[TestClient, User]:
    user, secret = make_user(role, email, **kwargs)
    client = new_client()
    login(client, outbox, email, secret=secret)
    return client, user


def make_cluster(code: str, head: User | None = None) -> Cluster:
    with session_factory()() as db:
        cluster = Cluster(code=code, name=f"Cluster {code}", cluster_head_id=head.id if head else None)
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        return cluster


def make_school(cluster: Cluster, code: str, name: str | None = None) -> School:
    name = name or f"School {code}"
    with session_factory()() as db:
        school = School(
            cluster_id=cluster.id,
            code=code,
            name=name,
            name_search=fold_search(name),
            address="Street 1",
            school_type="primary",
            medium="arabic",
            contact_phone="+96500000000",
        )
        db.add(school)
        db.commit()
        db.refresh(school)
        return school


def seed_reference() -> None:
    values = {
        "designation": [("T1", "Teacher", "معلم"), ("HT", "Head of Department", "رئيس قسم")],
        "subject": [
            ("MATH", "Mathematics", "الرياضيات"),
            ("ARB", "Arabic", "اللغة العربية"),
            ("SCI", "Science", "العلوم"),
        ],
        "class": [("G1", "Grade 1", "الصف الأول"), ("G2", "Grade 2", "الصف الثاني")],
        "qualification": [("BED", "B.Ed", "بكالوريوس تربية"), ("MED", "M.Ed", "ماجستير تربية")],
    }
    with session_factory()() as db:
        for list_name, rows in values.items():
            for code, en, ar in rows:
                db.add(ReferenceValue(list_name=list_name, code=code, name_en=en, name_ar=ar))
        db.commit()


def teacher_body(school_id: int, staff_id: str = "T-100", email: str = "teacher@example.org", **overrides) -> dict:
    body = {
        "staff_id": staff_id,
        "name": "Fatima Al-Sabah",
        "email": email,
        "school_id": school_id,
        "designation": "T1",
        "subjects": ["MATH", "SCI"],
        "classes": ["G1"],
        "experience_years": 7,
        "experience_as_of": "2026-09-01",
        "qualifications": [{"code": "BED", "year": 2015}],
    }
    body.update(overrides)
    return body


def user_by_email(email: str) -> User:
    with session_factory()() as db:
        return db.execute(select(User).where(User.email == email)).scalar_one()


def text(en: str, ar: str) -> dict:
    return {"en": en, "ar": ar}


def sample_schema(*, arabic: bool = True, teacher_section: bool = False) -> dict:
    """A small complete form: a supervisor section with every common question type."""
    ar = (lambda s: s) if arabic else (lambda s: "")
    sections = [
        {
            "key": "visit",
            "title": text("Visit", ar("الزيارة")),
            "respondent": "supervisor",
            "questions": [
                {
                    "key": "met_principal",
                    "type": "yes_no",
                    "label": text("Met the principal?", ar("هل قابلت المدير؟")),
                    "required": True,
                },
                {
                    "key": "reason_not_met",
                    "type": "short_text",
                    "label": text("Why not?", ar("لماذا لا؟")),
                    "required": True,
                    "visible_if": {"question": "met_principal", "op": "equals", "value": False},
                },
                {
                    "key": "classrooms",
                    "type": "number",
                    "label": text("Classrooms visited", ar("الفصول التي زرتها")),
                    "required": True,
                    "min": 0,
                    "max": 50,
                    "score_weight": 2,
                },
                {
                    "key": "rating",
                    "type": "rating",
                    "label": text("Overall", ar("التقييم العام")),
                    "min": 1,
                    "max": 5,
                    "required": True,
                },
                {
                    "key": "areas",
                    "type": "multi_choice",
                    "label": text("Areas", ar("المجالات")),
                    "options": [
                        {"code": "safety", "label": text("Safety", ar("السلامة"))},
                        {"code": "teaching", "label": text("Teaching", ar("التدريس"))},
                    ],
                },
                {
                    "key": "staff",
                    "type": "table",
                    "label": text("Staff present", ar("الموظفون الحاضرون")),
                    "columns": [
                        {"key": "name", "type": "short_text", "label": text("Name", ar("الاسم")), "required": True},
                        {"key": "present", "type": "yes_no", "label": text("Present", ar("حاضر"))},
                    ],
                },
                {"key": "notes", "type": "long_text", "label": text("Notes", ar("ملاحظات"))},
            ],
        }
    ]
    if teacher_section:
        sections.append(
            {
                "key": "self",
                "title": text("Teacher input", ar("مدخلات المعلم")),
                "respondent": "teacher",
                "questions": [{"key": "comment", "type": "long_text", "label": text("Comment", ar("تعليق"))}],
            }
        )
    return {"sections": sections}
