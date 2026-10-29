"""Global search across schools, teachers, supervisors, evaluations and scanned report details,
within the user's scope (FR-RP1).

Each group is the screen's own scoped list with a search term, so search can never show more
than those lists would. Groups a role has no list for are left out rather than asked, so a
search never records a permission denial for a page the user cannot open anyway.
"""

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased

from app.auth.deps import Principal
from app.documents import service as documents
from app.errors import AppError
from app.evaluations import service as evaluations
from app.models import Evaluation, FormVersion, MinistryReport, MinistryReportVersion, Role, School, Teacher, User
from app.structure import people
from app.structure import service as structure
from app.structure.common import like_pattern
from app.structure.service import paginate

PER_GROUP = 5
GROUPS = {
    Role.DISTRICT_ADMIN: ("schools", "teachers", "supervisors", "evaluations", "documents"),
    Role.CLUSTER_HEAD: ("schools", "teachers", "supervisors", "evaluations", "documents"),
    Role.SUPERVISOR: ("schools", "teachers", "evaluations", "documents"),
}


def _evaluations(db: Session, principal: Principal, q: str) -> dict[str, Any]:
    teacher_user = aliased(User)
    pattern = like_pattern(q)
    query = (
        evaluations.visible_query(db, principal)
        .join(School, School.id == Evaluation.school_id)
        .join(FormVersion, FormVersion.id == Evaluation.form_version_id)
        .join(MinistryReportVersion, MinistryReportVersion.id == FormVersion.ministry_report_version_id)
        .join(MinistryReport, MinistryReport.id == MinistryReportVersion.ministry_report_id)
        .outerjoin(Teacher, Teacher.id == Evaluation.teacher_id)
        .outerjoin(teacher_user, teacher_user.id == Teacher.user_id)
        .where(
            or_(
                School.name_search.like(pattern),
                School.code.like(f"%{q.strip()}%"),
                MinistryReport.report_code.like(f"%{q.strip()}%"),
                teacher_user.name_search.like(pattern),
            )
        )
        .order_by(Evaluation.id.desc())
    )
    rows, total = paginate(db, query, 1, PER_GROUP)
    return {"items": [evaluations.evaluation_out(db, e, full=False) for (e,) in rows], "total": total}


def search(db: Session, principal: Principal, q: str) -> dict[str, Any]:
    groups = GROUPS.get(principal.role)
    if groups is None:
        raise AppError(403, "forbidden")
    term = q.strip()
    if len(term) < 2:
        return {group: {"items": [], "total": 0} for group in groups}
    out: dict[str, Any] = {}
    for group in groups:
        if group == "schools":
            found = structure.list_schools(db, principal, q=term, page_size=PER_GROUP)
        elif group == "teachers":
            found = people.list_teachers(db, principal, q=term, page_size=PER_GROUP)
        elif group == "supervisors":
            found = people.list_supervisors(db, principal, q=term, page_size=PER_GROUP)
        elif group == "evaluations":
            found = _evaluations(db, principal, term)
        else:
            found = documents.list_documents(db, principal, q=term, page_size=PER_GROUP)
        out[group] = {"items": found["items"], "total": found["total"]}
    return out
