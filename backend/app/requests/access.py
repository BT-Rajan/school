"""Who can see a teacher request: the one rule every code path uses (FR-E10, FR-R1).

- A teacher sees only requests addressed to them now. They never see the
  supervisor's sections of the evaluation, only their own.
- A supervisor sees the requests they made and those of evaluations they own.
- A Cluster Head sees requests for schools in the clusters they head now, and
  is the one who may waive them.
- District Admins see every request.
- Nobody else sees anything: not other teachers, not Form Authors.

A request keeps its school when the teacher transfers, so the requester and the
original Cluster Head keep their view (section 6.1).
"""

from sqlalchemy import Select, false, or_, select
from sqlalchemy.orm import Session

from app.assignments import queries as assignments
from app.auth.deps import Principal
from app.errors import not_found
from app.models import Evaluation, Role, School, Teacher, TeacherRequest
from app.structure.common import deny, managed_cluster_ids


def teacher_for_user(db: Session, user_id: int) -> Teacher | None:
    return db.execute(select(Teacher).where(Teacher.user_id == user_id)).scalar_one_or_none()


def visible_query(db: Session, principal: Principal) -> Select:
    query = select(TeacherRequest)
    if principal.role == Role.DISTRICT_ADMIN:
        return query
    if principal.role == Role.TEACHER:
        teacher = teacher_for_user(db, principal.user.id)
        if teacher is None:
            return query.where(false())
        return query.where(TeacherRequest.teacher_id == teacher.id)
    if principal.role == Role.SUPERVISOR:
        own = assignments.supervisor_for_user(db, principal.user.id)
        owned_evaluations = (
            select(Evaluation.id).where(Evaluation.supervisor_id == own.id)
            if own
            else select(Evaluation.id).where(false())
        )
        return query.where(
            or_(TeacherRequest.requested_by == principal.user.id, TeacherRequest.evaluation_id.in_(owned_evaluations))
        )
    if principal.role == Role.CLUSTER_HEAD:
        clusters = managed_cluster_ids(db, principal) or []
        return query.where(TeacherRequest.school_id.in_(select(School.id).where(School.cluster_id.in_(clusters))))
    return query.where(false())


def get_visible(db: Session, principal: Principal, request_id: int) -> TeacherRequest:
    """A request the principal may see. Anything else is 404, and the attempt is audited."""
    found = db.execute(visible_query(db, principal).where(TeacherRequest.id == request_id)).scalar_one_or_none()
    if found is None:
        if db.get(TeacherRequest, request_id) is not None:
            deny(db, "request", request_id)
        raise not_found()
    return found


def is_respondent(db: Session, principal: Principal, r: TeacherRequest) -> bool:
    if principal.role != Role.TEACHER:
        return False
    teacher = teacher_for_user(db, principal.user.id)
    return teacher is not None and teacher.id == r.teacher_id


def is_requester(db: Session, principal: Principal, r: TeacherRequest) -> bool:
    """The requester: who asked, or for an evaluation, the supervisor who owns it now."""
    if r.evaluation_id is not None:
        if principal.role != Role.SUPERVISOR:
            return False
        own = assignments.supervisor_for_user(db, principal.user.id)
        e = db.get(Evaluation, r.evaluation_id)
        return own is not None and e is not None and e.supervisor_id == own.id
    return r.requested_by == principal.user.id


def can_waive(db: Session, principal: Principal, r: TeacherRequest) -> bool:
    """FR-E6: the Cluster Head of the school's cluster, or a District Admin."""
    if principal.role == Role.DISTRICT_ADMIN:
        return True
    if principal.role != Role.CLUSTER_HEAD:
        return False
    return db.get(School, r.school_id).cluster_id in (managed_cluster_ids(db, principal) or [])
