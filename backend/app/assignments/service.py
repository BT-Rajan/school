"""Assign, unassign and reassign supervisors to schools (section 7).

Every write locks the school's row first, so writes for one school are
serialized and two overlapping assignments can never both be created.
Changes to an existing assignment also carry its version: a stale version
gets 409 with the current state (FR-AS7).
"""

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.auth.deps import Principal
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.evaluations import drafts
from app.models import Cluster, EntityStatus, Role, School, Supervisor, SupervisorAssignment, User
from app.structure.common import deny, managed_cluster_ids

from . import queries

DraftChoice = Literal["transfer", "cancel"]


class AssignIn(BaseModel):
    supervisor_id: int
    school_id: int
    start_date: date | None = None
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=500)


class UnassignIn(BaseModel):
    version: int
    end_date: date | None = None
    reason: str = Field(min_length=1, max_length=500)
    drafts: DraftChoice | None = None
    transfer_to_supervisor_id: int | None = None


class ReassignIn(BaseModel):
    version: int
    to_supervisor_id: int
    effective_date: date | None = None
    reason: str = Field(min_length=1, max_length=500)
    drafts: DraftChoice | None = None


def _today(db: Session) -> date:
    return clock.local_date(get_district(db).time_zone)


def assignment_out(db: Session, a: SupervisorAssignment) -> dict[str, Any]:
    supervisor = db.get(Supervisor, a.supervisor_id)
    user = db.get(User, supervisor.user_id)
    school = db.get(School, a.school_id)
    today = _today(db)
    if a.end_date is not None and a.end_date < today:
        state = "ended"
    elif a.start_date > today:
        state = "upcoming"
    else:
        state = "active"
    return {
        "id": a.id,
        "supervisor": {"id": supervisor.id, "name": user.name, "staff_id": user.staff_id},
        "school": {"id": school.id, "code": school.code, "name": school.name},
        "start_date": a.start_date,
        "end_date": a.end_date,
        "state": state,
        "reason": a.reason,
        "end_reason": a.end_reason,
        "version": a.version,
    }


def _lock_school(db: Session, principal: Principal, school_id: int) -> School:
    school = db.execute(select(School).where(School.id == school_id).with_for_update()).scalar_one_or_none()
    if school is None:
        raise not_found()
    allowed = managed_cluster_ids(db, principal)
    if allowed is not None and school.cluster_id not in allowed:
        deny(db, "school", school_id)
    return school


def _usable_supervisor(db: Session, supervisor_id: int, cluster_id: int) -> Supervisor:
    supervisor = db.get(Supervisor, supervisor_id)
    if supervisor is None or supervisor.status != EntityStatus.ACTIVE:
        raise invalid("supervisor_unknown")
    if supervisor.cluster_id != cluster_id:
        raise invalid("supervisor_other_cluster")
    return supervisor


def _check_overlap(db: Session, supervisor_id: int, school_id: int, start: date, end: date | None) -> None:
    """FR-AS1: the same supervisor and school may not have overlapping windows."""
    query = select(SupervisorAssignment.id).where(
        SupervisorAssignment.supervisor_id == supervisor_id,
        SupervisorAssignment.school_id == school_id,
        or_(SupervisorAssignment.end_date.is_(None), SupervisorAssignment.end_date >= start),
        # Ended-before-start rows are cancelled future assignments and never overlap.
        or_(SupervisorAssignment.end_date.is_(None), SupervisorAssignment.end_date >= SupervisorAssignment.start_date),
    )
    if end is not None:
        query = query.where(SupervisorAssignment.start_date <= end)
    if db.execute(query).first():
        raise AppError(409, "assignment_overlap")


def _locked_assignment(db: Session, principal: Principal, assignment_id: int, version: int) -> SupervisorAssignment:
    current = db.get(SupervisorAssignment, assignment_id)
    if current is None:
        raise not_found()
    _lock_school(db, principal, current.school_id)
    # A locking read sees the latest committed row; a plain read would return this
    # transaction's older snapshot (REPEATABLE READ) and miss a concurrent change.
    current = db.execute(
        select(SupervisorAssignment)
        .where(SupervisorAssignment.id == assignment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if current.version != version:
        raise AppError(409, "version_conflict", {"current": assignment_out(db, current)})
    return current


def _handle_drafts(
    db: Session, a: SupervisorAssignment, choice: DraftChoice | None, target_supervisor_id: int | None, reason: str
) -> dict[str, Any]:
    """FR-AS2: drafts on the school need an explicit choice before the assignment ends."""
    ids = drafts.open_draft_ids(db, a.supervisor_id, a.school_id)
    if not ids:
        return {}
    if choice is None:
        raise AppError(409, "drafts_open", {"count": len(ids)})
    if choice == "transfer":
        if target_supervisor_id is None or not queries.windows(db, target_supervisor_id, a.school_id):
            raise invalid("transfer_target_not_assigned")
        drafts.transfer(db, ids, target_supervisor_id)
        return {"drafts_transferred": ids, "to_supervisor_id": target_supervisor_id}
    drafts.cancel(db, ids, reason)
    return {"drafts_cancelled": ids}


def assign(db: Session, principal: Principal, body: AssignIn, *, commit: bool = True) -> SupervisorAssignment:
    school = _lock_school(db, principal, body.school_id)
    if school.status != EntityStatus.ACTIVE:
        raise invalid("school_inactive")
    _usable_supervisor(db, body.supervisor_id, school.cluster_id)
    start = body.start_date or _today(db)
    if body.end_date is not None and body.end_date < start:
        raise invalid("end_before_start")
    _check_overlap(db, body.supervisor_id, school.id, start, body.end_date)
    a = SupervisorAssignment(
        supervisor_id=body.supervisor_id,
        school_id=school.id,
        start_date=start,
        end_date=body.end_date,
        reason=body.reason,
        created_by=principal.user.id,
    )
    db.add(a)
    db.flush()
    audit.record(
        db,
        "assignment.created",
        entity_type="assignment",
        entity_id=a.id,
        cluster_id=school.cluster_id,
        after={"supervisor_id": a.supervisor_id, "school_id": a.school_id, "start": a.start_date, "end": a.end_date},
    )
    from app.notifications import service as notify

    notify.assignment_changed(db, a.supervisor_id, "assignment_started", school, a.start_date)
    if commit:
        db.commit()
    return a


def _end(db: Session, principal: Principal, a: SupervisorAssignment, end: date, reason: str) -> None:
    # Ending a future assignment before it starts leaves an empty window, kept for the record.
    a.end_date = max(a.start_date - timedelta(days=1), end)
    a.end_reason = reason
    a.ended_by = principal.user.id
    a.ended_at = clock.now()


def unassign(db: Session, principal: Principal, assignment_id: int, body: UnassignIn) -> SupervisorAssignment:
    a = _locked_assignment(db, principal, assignment_id, body.version)
    today = _today(db)
    if a.end_date is not None and a.end_date < today:
        raise invalid("assignment_already_ended")
    end = body.end_date or today
    if end < today:
        raise invalid("end_in_past")
    outcome = _handle_drafts(db, a, body.drafts, body.transfer_to_supervisor_id, body.reason)
    _end(db, principal, a, end, body.reason)
    db.flush()
    school = db.get(School, a.school_id)
    audit.record(
        db,
        "assignment.ended",
        entity_type="assignment",
        entity_id=a.id,
        cluster_id=school.cluster_id,
        after={"end": a.end_date, "reason": body.reason, **outcome},
    )
    from app.notifications import service as notify

    notify.assignment_changed(db, a.supervisor_id, "assignment_ended", school, a.end_date)
    db.commit()
    return a


def reassign(db: Session, principal: Principal, assignment_id: int, body: ReassignIn) -> SupervisorAssignment:
    """FR-AS3: end A and start B in one transaction, keeping both in history."""
    a = _locked_assignment(db, principal, assignment_id, body.version)
    today = _today(db)
    if a.end_date is not None and a.end_date < today:
        raise invalid("assignment_already_ended")
    if body.to_supervisor_id == a.supervisor_id:
        raise invalid("same_supervisor")
    effective = body.effective_date or today
    if effective < today:
        raise invalid("start_in_past")
    school = db.get(School, a.school_id)
    _usable_supervisor(db, body.to_supervisor_id, school.cluster_id)
    _end(db, principal, a, effective - timedelta(days=1), body.reason)
    db.flush()
    b_end = None
    _check_overlap(db, body.to_supervisor_id, school.id, max(effective, a.start_date), b_end)
    b = SupervisorAssignment(
        supervisor_id=body.to_supervisor_id,
        school_id=school.id,
        start_date=max(effective, a.start_date),
        reason=body.reason,
        created_by=principal.user.id,
    )
    db.add(b)
    db.flush()
    outcome = _handle_drafts(db, a, body.drafts, b.supervisor_id, body.reason)
    audit.record(
        db,
        "assignment.reassigned",
        entity_type="assignment",
        entity_id=a.id,
        cluster_id=school.cluster_id,
        before={"supervisor_id": a.supervisor_id},
        after={"supervisor_id": b.supervisor_id, "new_assignment_id": b.id, "effective": b.start_date, **outcome},
    )
    from app.notifications import service as notify

    notify.assignment_changed(db, a.supervisor_id, "assignment_ended", school, a.end_date)
    notify.assignment_changed(db, b.supervisor_id, "assignment_started", school, b.start_date)
    db.commit()
    return b


def history(
    db: Session, principal: Principal, *, school_id: int | None = None, supervisor_id: int | None = None
) -> list[dict[str, Any]]:
    """FR-AS5: who was assigned, when, by whom, and why."""
    if school_id is None and supervisor_id is None:
        raise invalid("filter_required")
    query = select(SupervisorAssignment).order_by(
        SupervisorAssignment.start_date.desc(), SupervisorAssignment.id.desc()
    )
    allowed = managed_cluster_ids(db, principal)
    if principal.role == Role.SUPERVISOR:
        own = queries.supervisor_for_user(db, principal.user.id)
        if own is None or (supervisor_id is not None and supervisor_id != own.id):
            deny(db, "supervisor", supervisor_id)
        query = query.where(SupervisorAssignment.supervisor_id == own.id)
    elif allowed is not None:
        query = query.join(School, School.id == SupervisorAssignment.school_id).where(School.cluster_id.in_(allowed))
    if school_id is not None:
        query = query.where(SupervisorAssignment.school_id == school_id)
    if supervisor_id is not None:
        query = query.where(SupervisorAssignment.supervisor_id == supervisor_id)
    rows = []
    for a in db.execute(query).scalars():
        out = assignment_out(db, a)
        creator = db.get(User, a.created_by)
        ender = db.get(User, a.ended_by) if a.ended_by else None
        out["created_by"] = creator.name if creator else None
        out["created_at"] = a.created_at
        out["ended_by"] = ender.name if ender else None
        out["ended_at"] = a.ended_at
        rows.append(out)
    return rows


def board(db: Session, principal: Principal, cluster_id: int) -> dict[str, Any]:
    """FR-AS4: schools against supervisors for one cluster."""
    allowed = managed_cluster_ids(db, principal)
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise not_found()
    if allowed is not None and cluster_id not in allowed:
        deny(db, "cluster", cluster_id)
    today = _today(db)
    schools = db.execute(
        select(School)
        .where(School.cluster_id == cluster_id, School.status == EntityStatus.ACTIVE)
        .order_by(School.code)
    ).scalars()
    current = db.execute(
        select(SupervisorAssignment)
        .join(School, School.id == SupervisorAssignment.school_id)
        .where(School.cluster_id == cluster_id, queries.not_ended(today))
        .where(
            or_(
                SupervisorAssignment.end_date.is_(None),
                SupervisorAssignment.end_date >= SupervisorAssignment.start_date,
            )
        )
    ).scalars()
    by_school: dict[int, list[dict[str, Any]]] = {}
    workload: dict[int, int] = {}
    for a in current:
        out = assignment_out(db, a)
        by_school.setdefault(a.school_id, []).append(out)
        if out["state"] == "active":
            workload[a.supervisor_id] = workload.get(a.supervisor_id, 0) + 1
    supervisors = db.execute(
        select(Supervisor, User)
        .join(User, User.id == Supervisor.user_id)
        .where(Supervisor.cluster_id == cluster_id, Supervisor.status == EntityStatus.ACTIVE)
        .order_by(User.name_search)
    ).all()
    return {
        "cluster": {"id": cluster.id, "code": cluster.code, "name": cluster.name},
        "schools": [
            {"id": s.id, "code": s.code, "name": s.name, "assignments": by_school.get(s.id, [])} for s in schools
        ],
        "supervisors": [
            {"id": s.id, "name": u.name, "staff_id": u.staff_id, "active_schools": workload.get(s.id, 0)}
            for s, u in supervisors
        ],
    }


def my_assignments(db: Session, principal: Principal) -> list[dict[str, Any]]:
    supervisor = queries.supervisor_for_user(db, principal.user.id)
    if supervisor is None:
        return []
    today = _today(db)
    rows = db.execute(
        select(SupervisorAssignment)
        .where(SupervisorAssignment.supervisor_id == supervisor.id, queries.not_ended(today))
        .order_by(SupervisorAssignment.start_date)
    ).scalars()
    return [assignment_out(db, a) for a in rows if a.end_date is None or a.end_date >= a.start_date]
