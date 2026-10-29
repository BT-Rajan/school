"""Seed for the Phase 3 browser test (e2e/phase3.cjs), on top of the Phase 2 seed.

Adds teachers who can sign in, assigns Noura to both schools, makes Fatima the
contact teacher of Al-Nahda Primary, and publishes a school visit form whose last
section is answered by the contact teacher. Never run it against production.

Usage, from backend/ with the app's environment set and migrations applied:
  PYTHONPATH=.:../e2e .venv/bin/python ../e2e/seed_phase3.py > seed.json
"""

import json
from datetime import timedelta

import pyotp
from seed_phase2 import PASSWORD, seed
from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.models import (
    FormVersion,
    MfaMethod,
    MinistryReport,
    MinistryReportVersion,
    ReferenceValue,
    Role,
    School,
    SchoolContact,
    Supervisor,
    SupervisorAssignment,
    Teacher,
    User,
    UserStatus,
)
from app.security import crypto, passwords
from app.structure.common import fold_search


def text(en: str, ar: str) -> dict:
    return {"en": en, "ar": ar}


SCHEMA = {
    "sections": [
        {
            "key": "visit",
            "title": text("Visit", "الزيارة"),
            "respondent": "supervisor",
            "questions": [
                {
                    "key": "overall",
                    "type": "rating",
                    "label": text("Overall", "التقييم العام"),
                    "required": True,
                    "min": 1,
                    "max": 5,
                }
            ],
        },
        {
            "key": "school_input",
            "title": text("School's input", "مدخلات المدرسة"),
            "respondent": "teacher",
            "questions": [
                {
                    "key": "enrolment",
                    "type": "number",
                    "label": text("Pupils enrolled", "عدد الطلاب المسجلين"),
                    "required": True,
                    "min": 0,
                },
                {"key": "needs", "type": "long_text", "label": text("What the school needs", "احتياجات المدرسة")},
            ],
        },
    ]
}


def seed3() -> dict:
    out = seed()
    with session_factory()() as db:
        today = clock.local_date("Asia/Kuwait")
        admin = db.execute(select(User).where(User.role == Role.DISTRICT_ADMIN)).scalars().first()
        nahda = db.execute(select(School).where(School.code == "SCH-1")).scalar_one()
        firdous = db.execute(select(School).where(School.code == "SCH-2")).scalar_one()
        designation = db.execute(select(ReferenceValue).where(ReferenceValue.list_name == "designation")).scalar_one()

        def can_sign_in(user: User, key: str) -> None:
            secret = pyotp.random_base32()
            user.password_hash = passwords.hash_password(PASSWORD)
            user.mfa_method = MfaMethod.TOTP
            user.totp_secret_enc = crypto.encrypt(secret, context=f"totp:{user.id}")
            out["users"][key] = {"email": user.email, "secret": secret, "name": user.name}

        fatima = db.execute(select(User).where(User.email == "fatima@e2e.example.org")).scalar_one()
        can_sign_in(fatima, "fatima")
        fatima_teacher = db.execute(select(Teacher).where(Teacher.user_id == fatima.id)).scalar_one()
        for key, name, school, staff in (
            ("huda", "Huda Al-Rashid", nahda, "T-101"),
            ("salem", "Salem Al-Enezi", firdous, "T-200"),
        ):
            user = User(
                role=Role.TEACHER,
                email=f"{key}@e2e.example.org",
                name=name,
                name_search=fold_search(name),
                staff_id=staff,
                status=UserStatus.ACTIVE,
            )
            db.add(user)
            db.flush()
            can_sign_in(user, key)
            db.add(
                Teacher(
                    user_id=user.id,
                    school_id=school.id,
                    designation_id=designation.id,
                    experience_years=3,
                    experience_as_of=today,
                )
            )
        db.add(SchoolContact(school_id=nahda.id, teacher_id=fatima_teacher.id, start_date=today, created_by=admin.id))
        noura = db.execute(select(User).where(User.name == "Noura Al-Saleh")).scalar_one()
        supervisor = db.execute(select(Supervisor).where(Supervisor.user_id == noura.id)).scalar_one()
        for school in (nahda, firdous):
            db.add(
                SupervisorAssignment(
                    supervisor_id=supervisor.id,
                    school_id=school.id,
                    start_date=today - timedelta(days=30),
                    created_by=admin.id,
                )
            )
        report = MinistryReport(report_code="MOE-SV-02", subject_type="school", created_by=admin.id)
        db.add(report)
        db.flush()
        mrv = MinistryReportVersion(
            ministry_report_id=report.id,
            version_code="2026.1",
            title_en="School profile visit",
            title_ar="زيارة ملف المدرسة",
            created_by=admin.id,
        )
        db.add(mrv)
        db.flush()
        db.add(
            FormVersion(
                ministry_report_version_id=mrv.id,
                schema=SCHEMA,
                status="published",
                start_date=today - timedelta(days=1),
                end_date=today + timedelta(days=30),
                built_by=admin.id,
                published_by=admin.id,
                published_at=clock.now(),
            )
        )
        db.commit()
    return out


def main() -> None:
    print(json.dumps(seed3()))


if __name__ == "__main__":
    main()
