"""Data at the district design scale (section 15), for the load test (loadtest/run.py).

On top of the Phase 4 browser-test seed (whose users can sign in), adds 25 clusters, 500
schools, 500 supervisors each assigned to one school (with an earlier, ended assignment too),
10,000 teachers, 200,000 scanned reports, 50,000 evaluations and 20,000 teacher requests.

Rows are inserted in bulk, not through the services: this is about how lists and counts
behave with this much data, not about creating it. Every scanned report points at the same
small stored PDF, so downloads work without a terabyte of files. Never run it against
production.

Usage, from backend/ with the app's environment set and migrations applied:
  PYTHONPATH=.:../e2e .venv/bin/python ../loadtest/seed_scale.py > seed.json
"""

import io
import json
import random
import sys
from datetime import date, timedelta

import pikepdf
from sqlalchemy import insert, select

from app import clock
from app.auth import service as auth
from app.db import session_factory
from app.files import service as files
from app.models import (
    Cluster,
    Document,
    DocumentVersion,
    Evaluation,
    EvaluationSection,
    FormVersion,
    ReferenceValue,
    Role,
    School,
    Supervisor,
    SupervisorAssignment,
    Teacher,
    TeacherRequest,
    User,
    UserStatus,
)
from app.structure.common import fold_search

sys.path.insert(0, "../e2e")
from seed_phase3 import seed3  # noqa: E402

CLUSTERS = 25
SCHOOLS_PER_CLUSTER = 20
TEACHERS_PER_SCHOOL = 20
DOCUMENTS_PER_SUPERVISOR = 400
EVALUATIONS_PER_SUPERVISOR = 100
REQUESTS = 20_000
BATCH = 5000
STATUSES = ["draft"] * 1 + ["submitted"] * 2 + ["viewed"] * 2 + ["acknowledged"] * 12 + ["returned"] * 1


def chunks(rows: list[dict], size: int = BATCH):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def bulk(db, model, rows: list[dict]) -> None:
    for part in chunks(rows):
        db.execute(insert(model), part)
    db.commit()


def ids(db, model, column, values) -> dict:
    return {
        getattr(r, column): r.id for r in db.execute(select(model).where(getattr(model, column).in_(values))).scalars()
    }


def main() -> None:
    out = seed3()
    random.seed(7)
    now = clock.now()
    today = clock.local_date("Asia/Kuwait")
    with session_factory()() as db:
        admin = db.execute(select(User).where(User.role == Role.DISTRICT_ADMIN)).scalars().first()
        designation = db.execute(select(ReferenceValue).where(ReferenceValue.list_name == "designation")).scalar_one()
        form = db.execute(select(FormVersion).where(FormVersion.status == "published")).scalars().first()
        mrv_id = form.ministry_report_version_id

        # One small stored PDF that every scanned report version points at.
        pdf = pikepdf.new()
        for _ in range(10):
            pdf.add_blank_page()
        buffer = io.BytesIO()
        pdf.save(buffer)
        stored = files.store(db, admin.id, "scale.pdf", buffer.getvalue(), "application/pdf", 10, owner_type="document")
        stored.scan_status = "clean"
        db.commit()

        # Cluster Heads and clusters.
        heads = [
            {
                "role": Role.CLUSTER_HEAD,
                "email": f"head{c:02d}@scale.example.org",
                "name": f"Head {c:02d}",
                "name_search": fold_search(f"Head {c:02d}"),
                "staff_id": f"SCH-{c:02d}",
                "status": UserStatus.ACTIVE,
            }
            for c in range(1, CLUSTERS + 1)
        ]
        bulk(db, User, heads)
        head_ids = ids(db, User, "email", [h["email"] for h in heads])
        bulk(
            db,
            Cluster,
            [
                {
                    "code": f"L-{c:02d}",
                    "name": f"Scale cluster {c:02d}",
                    "cluster_head_id": head_ids[f"head{c:02d}@scale.example.org"],
                }
                for c in range(1, CLUSTERS + 1)
            ],
        )
        cluster_ids = ids(db, Cluster, "code", [f"L-{c:02d}" for c in range(1, CLUSTERS + 1)])

        # Schools.
        schools = []
        for c in range(1, CLUSTERS + 1):
            for s in range(1, SCHOOLS_PER_CLUSTER + 1):
                name = f"Scale School {c:02d}-{s:02d}"
                schools.append(
                    {
                        "cluster_id": cluster_ids[f"L-{c:02d}"],
                        "code": f"L{c:02d}-{s:02d}",
                        "name": name,
                        "name_search": fold_search(name),
                        "address": "Street",
                        "school_type": "primary",
                        "medium": "arabic",
                        "contact_phone": "+96500000000",
                        "custom": {},
                    }
                )
        bulk(db, School, schools)
        school_rows = list(db.execute(select(School).where(School.code.like("L%-%"))).scalars())
        print(f"schools: {len(school_rows)}", file=sys.stderr)

        # Supervisors, one per school, in the school's cluster; an ended assignment before the current one.
        sup_users = [
            {
                "role": Role.SUPERVISOR,
                "email": f"sup{i:03d}@scale.example.org",
                "name": f"Supervisor {i:03d}",
                "name_search": fold_search(f"Supervisor {i:03d}"),
                "staff_id": f"SS-{i:03d}",
                "status": UserStatus.ACTIVE,
            }
            for i in range(len(school_rows))
        ]
        bulk(db, User, sup_users)
        sup_user_ids = ids(db, User, "email", [u["email"] for u in sup_users])
        bulk(
            db,
            Supervisor,
            [
                {"user_id": sup_user_ids[f"sup{i:03d}@scale.example.org"], "cluster_id": school.cluster_id}
                for i, school in enumerate(school_rows)
            ],
        )
        supervisors = {
            s.user_id: s
            for s in db.execute(select(Supervisor).where(Supervisor.user_id.in_(sup_user_ids.values()))).scalars()
        }
        pairs = [
            (supervisors[sup_user_ids[f"sup{i:03d}@scale.example.org"]], school) for i, school in enumerate(school_rows)
        ]
        assignments = []
        for i, (sup, school) in enumerate(pairs):
            previous = pairs[(i + 1) % len(pairs)][0]
            assignments.append(
                {
                    "supervisor_id": previous.id,
                    "school_id": school.id,
                    "start_date": today - timedelta(days=700),
                    "end_date": today - timedelta(days=366),
                    "created_by": admin.id,
                }
            )
            assignments.append(
                {
                    "supervisor_id": sup.id,
                    "school_id": school.id,
                    "start_date": today - timedelta(days=365),
                    "created_by": admin.id,
                }
            )
        bulk(db, SupervisorAssignment, assignments)
        print(f"supervisors: {len(pairs)}", file=sys.stderr)
        # Signed-in sessions for the scale supervisors, so the realtime test can hold
        # connections from hundreds of different people, as in the district.
        scale_users = db.execute(select(User).where(User.id.in_(sup_user_ids.values()))).scalars()
        out["sessions"] = [auth.create_session(db, u) for u in scale_users]
        db.commit()
        # The seeded supervisor who signs in (Noura) carries a full share of work too.
        noura = db.execute(
            select(Supervisor).join(User, User.id == Supervisor.user_id).where(User.email.like("supa@%"))
        ).scalar_one()
        nahda = db.execute(select(School).where(School.code == "SCH-1")).scalar_one()
        working = [*pairs, (noura, nahda)]

        # Teachers.
        teacher_users = []
        for school in school_rows:
            for t in range(TEACHERS_PER_SCHOOL):
                name = f"Teacher {school.code} {t:02d}"
                teacher_users.append(
                    {
                        "role": Role.TEACHER,
                        "email": f"t-{school.code}-{t:02d}@scale.example.org".lower(),
                        "name": name,
                        "name_search": fold_search(name),
                        "staff_id": f"T-{school.code}-{t:02d}",
                        "status": UserStatus.ACTIVE,
                    }
                )
        bulk(db, User, teacher_users)
        emails = [u["email"] for u in teacher_users]
        teacher_user_ids: dict[str, int] = {}
        for part in range(0, len(emails), BATCH):
            teacher_user_ids |= ids(db, User, "email", emails[part : part + BATCH])
        teachers = []
        for school in school_rows:
            for t in range(TEACHERS_PER_SCHOOL):
                teachers.append(
                    {
                        "user_id": teacher_user_ids[f"t-{school.code}-{t:02d}@scale.example.org".lower()],
                        "school_id": school.id,
                        "designation_id": designation.id,
                        "experience_years": t % 25,
                        "experience_as_of": today,
                        "custom": {},
                    }
                )
        bulk(db, Teacher, teachers)
        teacher_rows = list(
            db.execute(
                select(Teacher.id, Teacher.school_id).where(Teacher.school_id.in_([s.id for s in school_rows]))
            ).all()
        )
        nahda_teachers = list(db.execute(select(Teacher.id).where(Teacher.school_id == nahda.id)).scalars())
        by_school: dict[int, list[int]] = {nahda.id: (nahda_teachers * TEACHERS_PER_SCHOOL)[:TEACHERS_PER_SCHOOL]}
        for tid, sid in teacher_rows:
            by_school.setdefault(sid, []).append(tid)
        print(f"teachers: {len(teacher_rows)}", file=sys.stderr)

        # Scanned reports with one version each.
        docs = []
        for sup, school in working:
            for d in range(DOCUMENTS_PER_SUPERVISOR):
                status = STATUSES[d % len(STATUSES)]
                day = today - timedelta(days=d % 700)
                submitted = None if status == "draft" else now - timedelta(days=d % 700, hours=2)
                docs.append(
                    {
                        "owner_supervisor_id": sup.id,
                        "cluster_id": school.cluster_id,
                        "school_id": school.id,
                        "teacher_id": by_school[school.id][d % TEACHERS_PER_SCHOOL] if d % 5 == 0 else None,
                        "ministry_report_version_id": mrv_id,
                        "title": f"Visit report {school.code} {d}",
                        "report_date": day,
                        "tags": [],
                        "status": status,
                        "submitted_at": submitted,
                        "acknowledged_at": submitted if status == "acknowledged" else None,
                        "acknowledged_by": admin.id if status == "acknowledged" else None,
                        "retention_until": date(day.year + 7, day.month, min(day.day, 28)),
                    }
                )
        for part in chunks(docs, 20000):
            bulk(db, Document, part)
        doc_ids = list(
            db.execute(
                select(Document.id, Document.owner_supervisor_id).where(Document.title.like("Visit report %"))
            ).all()
        )
        owner_user = {s.id: s.user_id for s in supervisors.values()} | {noura.id: noura.user_id}
        versions = [
            {"document_id": did, "version_no": 1, "stored_file_id": stored.id, "created_by": owner_user[sid]}
            for did, sid in doc_ids
        ]
        for part in chunks(versions, 20000):
            bulk(db, DocumentVersion, part)
        db.execute(
            Document.__table__.update()
            .where(Document.title.like("Visit report %"))
            .values(
                current_version_id=select(DocumentVersion.id)
                .where(DocumentVersion.document_id == Document.id)
                .scalar_subquery()
            )
        )
        db.commit()
        print(f"documents: {len(doc_ids)}", file=sys.stderr)

        # Evaluations, with their supervisor section.
        evaluations = []
        for sup, school in working:
            for e in range(EVALUATIONS_PER_SUPERVISOR):
                status = "draft" if e % 10 == 0 else ("cancelled" if e % 25 == 0 else "submitted")
                day = today - timedelta(days=e * 3)
                percent = round(50 + (e * 7 % 50) + 0.5, 2)
                evaluations.append(
                    {
                        "form_version_id": form.id,
                        "subject_type": "school",
                        "school_id": school.id,
                        "supervisor_id": sup.id,
                        "status": status,
                        "visit_date": day,
                        "submitted_at": now - timedelta(days=e * 3) if status == "submitted" else None,
                        "score": {
                            "points": percent,
                            "max": 100,
                            "percent": percent,
                            "band": None,
                            "sections": {},
                            "rule_set_id": 0,
                            "rule_set_number": 1,
                            "calculated_at": now.isoformat(),
                        }
                        if status == "submitted"
                        else None,
                    }
                )
        for part in chunks(evaluations, 20000):
            bulk(db, Evaluation, part)
        eval_ids = list(
            db.execute(
                select(Evaluation.id).where(Evaluation.school_id.in_([s.id for s in school_rows] + [nahda.id]))
            ).scalars()
        )
        bulk(
            db,
            EvaluationSection,
            [
                {
                    "evaluation_id": eid,
                    "section_key": "visit",
                    "respondent": "supervisor",
                    "status": "submitted",
                    "answers": {"rating": 4, "met_principal": True},
                }
                for eid in eval_ids
            ],
        )
        print(f"evaluations: {len(eval_ids)}", file=sys.stderr)

        # Standalone teacher requests.
        requests = []
        for r in range(REQUESTS):
            sup, school = pairs[r % len(pairs)]
            status = ["not_started", "in_progress", "submitted", "submitted", "submitted", "waived", "cancelled"][r % 7]
            requests.append(
                {
                    "kind": "standalone",
                    "form_version_id": form.id,
                    "school_id": school.id,
                    "via_contact": False,
                    "teacher_id": by_school[school.id][r % TEACHERS_PER_SCHOOL],
                    "requested_by": owner_user[sup.id],
                    "due_date": today + timedelta(days=(r % 60) - 30),
                    "status": status,
                    "answers": {},
                    "return_count": 0,
                    "reminders": [],
                }
            )
        bulk(db, TeacherRequest, requests)
        print(f"requests: {len(requests)}", file=sys.stderr)
    out["scale"] = {
        "schools": len(school_rows),
        "teachers": len(teacher_rows),
        "supervisors": len(pairs),
        "documents": len(doc_ids),
        "evaluations": len(eval_ids),
        "requests": len(requests),
        "file_id": stored.id,
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()
