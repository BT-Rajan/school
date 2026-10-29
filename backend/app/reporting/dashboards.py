"""Dashboards by role (FR-RP2). Counts come from the same scoped queries as the lists.

- Admin: the district at a glance, audit chain, report inbox, coverage by ministry report, forms
  and their windows, mail budget, storage and quarantined files.
- Cluster Head: their clusters' unassigned schools, evaluation progress by school, supervisor
  workload, overdue requests, schools without a contact teacher, reports forwarded to them.
- Supervisor: upcoming visits, drafts, completed evaluations, and their report counts.
- Teacher: pending requests with due dates.
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app import clock
from app.assignments import queries as assignment_queries
from app.audit import service as audit
from app.auth.deps import Principal
from app.district import get_district
from app.documents import access as documents_access
from app.errors import AppError
from app.evaluations import service as evaluations
from app.mail import queue as mail
from app.models import (
    Cluster,
    Document,
    Evaluation,
    FormVersion,
    MinistryReport,
    MinistryReportVersion,
    Role,
    School,
    SchoolContact,
    StoredFile,
    Supervisor,
    SupervisorAssignment,
    Teacher,
    TeacherRequest,
    User,
)
from app.models.enums import EntityStatus
from app.requests import access as requests_access
from app.requests import service as requests
from app.structure.common import managed_cluster_ids

ACTIVE = EntityStatus.ACTIVE
DONE = ("submitted", "amended")
UNDER_REVIEW = ("submitted", "viewed")


def _today(db: Session) -> date:
    return clock.local_date(get_district(db).time_zone)


def _count(db: Session, query) -> int:
    return int(db.execute(select(func.count()).select_from(query.subquery())).scalar_one())


def _active_forms(db: Session, today: date) -> list[tuple[FormVersion, MinistryReportVersion, MinistryReport]]:
    out = []
    for form in db.execute(select(FormVersion).where(FormVersion.status == "published")).scalars():
        if form.effective_status(today) != "active":
            continue
        mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
        out.append((form, mrv, db.get(MinistryReport, mrv.ministry_report_id)))
    return out


def _report_ref(mrv: MinistryReportVersion, report: MinistryReport) -> dict[str, Any]:
    return {
        "code": report.report_code,
        "version_code": mrv.version_code,
        "title_en": mrv.title_en,
        "title_ar": mrv.title_ar,
    }


def _overdue_requests(db: Session, principal: Principal, today: date) -> int:
    query = requests_access.visible_query(db, principal).where(
        TeacherRequest.status.in_(requests.OPEN), TeacherRequest.due_date < today
    )
    return _count(db, query)


# Admin ------------------------------------------------------------------------------------


def admin(db: Session, principal: Principal) -> dict[str, Any]:
    today = _today(db)
    district = get_district(db)
    schools_active = _count(db, select(School.id).where(School.status == ACTIVE))
    docs = documents_access.visible_query(db, principal).where(Document.deleted_at.is_(None))
    overdue_after = timedelta(days=int(district.setting("acknowledge_overdue_days")))
    inbox = db.execute(
        docs.with_only_columns(
            func.sum(case((Document.status == "submitted", 1), else_=0)),
            func.sum(case((Document.status == "viewed", 1), else_=0)),
            func.sum(case((Document.status == "returned", 1), else_=0)),
            func.sum(case((Document.status == "acknowledged", 1), else_=0)),
            func.sum(
                case(
                    (and_(Document.status.in_(UNDER_REVIEW), Document.submitted_at < clock.now() - overdue_after), 1),
                    else_=0,
                )
            ),
        )
    ).one()
    coverage = []
    for form, mrv, report in _active_forms(db, today):
        with_report = _count(
            db,
            select(Document.school_id)
            .where(
                Document.ministry_report_version_id == mrv.id,
                Document.deleted_at.is_(None),
                Document.status.in_(("submitted", "viewed", "acknowledged")),
            )
            .distinct(),
        )
        evaluated = _count(
            db,
            select(Evaluation.school_id)
            .where(Evaluation.form_version_id == form.id, Evaluation.status.in_(DONE))
            .distinct(),
        )
        coverage.append(
            {
                "report": _report_ref(mrv, report),
                "form_id": form.id,
                "schools": schools_active,
                "with_report": with_report,
                "evaluated": evaluated,
                "end_date": form.end_date,
            }
        )
    forms = []
    for form in db.execute(select(FormVersion).order_by(FormVersion.id.desc())).scalars():
        status = form.effective_status(today)
        if status in ("ended", "closed"):
            continue
        mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
        forms.append(
            {
                "id": form.id,
                "report": _report_ref(mrv, db.get(MinistryReport, mrv.ministry_report_id)),
                "status": status,
                "start_date": form.start_date,
                "end_date": form.end_date,
            }
        )
    latest = audit.latest_verification(db)
    storage = db.execute(
        select(func.count(StoredFile.id), func.coalesce(func.sum(StoredFile.size), 0)).where(
            StoredFile.deleted_at.is_(None)
        )
    ).one()
    return {
        "role": "district_admin",
        "counts": {
            "clusters": _count(db, select(Cluster.id).where(Cluster.status == ACTIVE)),
            "schools": schools_active,
            "teachers": _count(db, select(Teacher.id).where(Teacher.status == ACTIVE)),
            "supervisors": _count(db, select(Supervisor.id).where(Supervisor.status == ACTIVE)),
            "overdue_requests": _overdue_requests(db, principal, today),
        },
        "audit": (
            {
                "ok": latest.ok,
                "ran_at": latest.ran_at,
                "checked": latest.checked_count,
                "broken_at_seq": latest.broken_at_seq,
            }
            if latest
            else None
        ),
        "inbox": {
            "submitted": int(inbox[0] or 0),
            "viewed": int(inbox[1] or 0),
            "returned": int(inbox[2] or 0),
            "acknowledged": int(inbox[3] or 0),
            "overdue": int(inbox[4] or 0),
        },
        "coverage": coverage,
        "forms": forms,
        "mail": mail.usage_today(db),
        "storage": {"files": int(storage[0]), "bytes": int(storage[1])},
        "quarantined": _count(db, select(StoredFile.id).where(StoredFile.scan_status == "quarantined")),
    }


# Cluster Head -----------------------------------------------------------------------------


def cluster_head(db: Session, principal: Principal) -> dict[str, Any]:
    today = _today(db)
    clusters = managed_cluster_ids(db, principal) or []
    schools = list(
        db.execute(
            select(School).where(School.cluster_id.in_(clusters), School.status == ACTIVE).order_by(School.code)
        ).scalars()
    )
    school_ids = [s.id for s in schools]
    assigned = set(
        db.execute(
            select(SupervisorAssignment.school_id).where(
                SupervisorAssignment.school_id.in_(school_ids), assignment_queries.covering(today)
            )
        ).scalars()
    )
    with_contact = set(
        db.execute(
            select(SchoolContact.school_id).where(
                SchoolContact.school_id.in_(school_ids),
                SchoolContact.start_date <= today,
                (SchoolContact.end_date.is_(None)) | (SchoolContact.end_date >= today),
            )
        ).scalars()
    )
    active_form_ids = [f.id for f, _, _ in _active_forms(db, today)]
    progress_rows = db.execute(
        evaluations.visible_query(db, principal)
        .where(Evaluation.form_version_id.in_(active_form_ids))
        .with_only_columns(
            Evaluation.school_id,
            func.sum(case((Evaluation.status == "draft", 1), else_=0)),
            func.sum(case((Evaluation.status.in_(DONE), 1), else_=0)),
        )
        .group_by(Evaluation.school_id)
    ).all()
    progress = {school_id: (int(d or 0), int(s or 0)) for school_id, d, s in progress_rows}
    supervisors = db.execute(
        select(Supervisor, User)
        .join(User, User.id == Supervisor.user_id)
        .where(Supervisor.cluster_id.in_(clusters), Supervisor.status == ACTIVE)
        .order_by(User.name)
    ).all()
    month_start = today.replace(day=1)
    workload = []
    for sup, user in supervisors:
        current = assignment_queries.school_ids_for_supervisor(db, sup.id, today)
        counts = db.execute(
            select(
                func.sum(case((Evaluation.status == "draft", 1), else_=0)),
                func.sum(case((and_(Evaluation.status.in_(DONE), Evaluation.submitted_at >= month_start), 1), else_=0)),
            ).where(Evaluation.supervisor_id == sup.id)
        ).one()
        workload.append(
            {
                "id": sup.id,
                "name": user.name,
                "schools": len(current),
                "drafts": int(counts[0] or 0),
                "submitted_this_month": int(counts[1] or 0),
            }
        )
    forwarded = documents_access.visible_query(db, principal)
    return {
        "role": "cluster_head",
        "unassigned_schools": [{"id": s.id, "code": s.code, "name": s.name} for s in schools if s.id not in assigned],
        "without_contact": [{"id": s.id, "code": s.code, "name": s.name} for s in schools if s.id not in with_contact],
        "progress": [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "drafts": progress.get(s.id, (0, 0))[0],
                "submitted": progress.get(s.id, (0, 0))[1],
            }
            for s in schools
        ],
        "active_forms": len(active_form_ids),
        "workload": workload,
        "overdue_requests": _overdue_requests(db, principal, today),
        "forwarded_reports": _count(db, forwarded),
    }


# Supervisor and teacher ---------------------------------------------------------------------


def supervisor(db: Session, principal: Principal) -> dict[str, Any]:
    today = _today(db)
    mine = evaluations.visible_query(db, principal)
    drafts = list(db.execute(mine.where(Evaluation.status == "draft").order_by(Evaluation.visit_date)).scalars())
    upcoming = [e for e in drafts if e.visit_date and e.visit_date >= today]
    done = _count(db, mine.where(Evaluation.status.in_(DONE)))
    this_month = _count(db, mine.where(Evaluation.status.in_(DONE), Evaluation.submitted_at >= today.replace(day=1)))
    reports = db.execute(
        documents_access.visible_query(db, principal)
        .with_only_columns(Document.status, func.count())
        .group_by(Document.status)
    ).all()
    return {
        "role": "supervisor",
        "upcoming": [evaluations.evaluation_out(db, e, full=False) for e in upcoming[:10]],
        "drafts": [evaluations.evaluation_out(db, e, full=False) for e in drafts[:10]],
        "draft_count": len(drafts),
        "completed": done,
        "completed_this_month": this_month,
        "overdue_requests": _overdue_requests(db, principal, today),
        "reports": {status: int(n) for status, n in reports},
    }


def teacher(db: Session, principal: Principal) -> dict[str, Any]:
    pending = list(
        db.execute(
            requests_access.visible_query(db, principal)
            .where(TeacherRequest.status.in_(requests.OPEN))
            .order_by(TeacherRequest.due_date)
        ).scalars()
    )
    return {
        "role": "teacher",
        "pending": [requests.request_out(db, principal, r) for r in pending[:20]],
        "pending_count": len(pending),
    }


def dashboard(db: Session, principal: Principal) -> dict[str, Any]:
    if principal.role == Role.DISTRICT_ADMIN:
        return admin(db, principal)
    if principal.role == Role.CLUSTER_HEAD:
        return cluster_head(db, principal)
    if principal.role == Role.SUPERVISOR:
        return supervisor(db, principal)
    if principal.role == Role.TEACHER:
        return teacher(db, principal)
    raise AppError(403, "forbidden")
