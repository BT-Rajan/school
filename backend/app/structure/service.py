"""Clusters, schools and contact teachers (section 5).

Every function takes the acting principal and enforces scope itself, so the
API, imports and any later caller share one set of rules.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.assignments import queries as assignment_queries
from app.audit import service as audit
from app.auth.deps import Principal
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.models import Cluster, EntityStatus, Role, School, SchoolContact, Teacher, User, UserStatus

from .common import (
    check_version,
    deny,
    ensure_cluster_in_scope,
    fold_search,
    like_pattern,
    managed_cluster_ids,
    validate_custom,
)
from .schemas import ClusterIn, ClusterUpdate, SchoolIn, SchoolUpdate

MAX_PAGE_SIZE = 200


def paginate(db: Session, query, page: int, page_size: int) -> tuple[list[Any], int]:
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page = max(1, page)
    total = db.execute(select(func.count()).select_from(query.order_by(None).subquery())).scalar_one()
    rows = db.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total


# Clusters -----------------------------------------------------------------------


def cluster_out(cluster: Cluster, head: User | None = None) -> dict[str, Any]:
    return {
        "id": cluster.id,
        "code": cluster.code,
        "name": cluster.name,
        "cluster_head": {"id": head.id, "name": head.name, "email": head.email} if head else None,
        "status": cluster.status,
        "version": cluster.version,
    }


def _cluster_head(db: Session, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or user.role != Role.CLUSTER_HEAD or user.status == UserStatus.INACTIVE:
        raise invalid("cluster_head_invalid")
    return user


def get_cluster(db: Session, principal: Principal, cluster_id: int) -> Cluster:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise not_found()
    ensure_cluster_in_scope(db, principal, cluster.id, entity="cluster", entity_id=cluster_id)
    return cluster


def list_clusters(db: Session, principal: Principal) -> list[dict[str, Any]]:
    query = select(Cluster, User).outerjoin(User, User.id == Cluster.cluster_head_id).order_by(Cluster.code)
    allowed = managed_cluster_ids(db, principal)
    if allowed is not None:
        query = query.where(Cluster.id.in_(allowed))
    return [cluster_out(c, head) for c, head in db.execute(query).all()]


def create_cluster(db: Session, body: ClusterIn) -> dict[str, Any]:
    if db.execute(select(Cluster.id).where(Cluster.code == body.code)).first():
        raise AppError(409, "code_taken")
    head = _cluster_head(db, body.cluster_head_id)
    cluster = Cluster(code=body.code, name=body.name, cluster_head_id=body.cluster_head_id)
    db.add(cluster)
    db.flush()
    out = cluster_out(cluster, head)
    audit.record(
        db,
        "cluster.created",
        entity_type="cluster",
        entity_id=cluster.id,
        cluster_id=cluster.id,
        after={"code": cluster.code, "name": cluster.name, "cluster_head_id": cluster.cluster_head_id},
    )
    db.commit()
    return out


def update_cluster(db: Session, cluster_id: int, body: ClusterUpdate) -> dict[str, Any]:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise not_found()
    check_version(
        body.version,
        cluster.version,
        cluster_out(cluster, db.get(User, cluster.cluster_head_id) if cluster.cluster_head_id else None),
    )
    before = {"name": cluster.name, "cluster_head_id": cluster.cluster_head_id}
    if body.name is not None:
        cluster.name = body.name
    if "cluster_head_id" in body.model_fields_set:
        # FR-AS8: a vacancy is filled by pointing the cluster at another Cluster Head.
        _cluster_head(db, body.cluster_head_id)
        cluster.cluster_head_id = body.cluster_head_id
    after = {"name": cluster.name, "cluster_head_id": cluster.cluster_head_id}
    old, new = audit.changed_fields(before, after)
    db.flush()
    if new:
        audit.record(
            db,
            "cluster.updated",
            entity_type="cluster",
            entity_id=cluster.id,
            cluster_id=cluster.id,
            before=old,
            after=new,
        )
    out = cluster_out(cluster, db.get(User, cluster.cluster_head_id) if cluster.cluster_head_id else None)
    db.commit()
    return out


def set_cluster_status(db: Session, cluster_id: int, status: EntityStatus) -> dict[str, Any]:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise not_found()
    if status == EntityStatus.INACTIVE:
        active_schools = db.execute(
            select(func.count())
            .select_from(School)
            .where(School.cluster_id == cluster.id, School.status == EntityStatus.ACTIVE)
        ).scalar_one()
        if active_schools:
            raise AppError(409, "cluster_has_active_schools", {"count": active_schools})
    cluster.status = status
    db.flush()
    audit.record(
        db,
        f"cluster.{'deactivated' if status == EntityStatus.INACTIVE else 'reactivated'}",
        entity_type="cluster",
        entity_id=cluster.id,
        cluster_id=cluster.id,
    )
    out = cluster_out(cluster, db.get(User, cluster.cluster_head_id) if cluster.cluster_head_id else None)
    db.commit()
    return out


# Schools ------------------------------------------------------------------------


def school_out(db: Session, school: School, cluster: Cluster | None = None) -> dict[str, Any]:
    cluster = cluster or db.get(Cluster, school.cluster_id)
    contact = current_contact(db, school.id)
    contact_user = db.get(User, db.get(Teacher, contact.teacher_id).user_id) if contact else None
    return {
        "id": school.id,
        "code": school.code,
        "name": school.name,
        "cluster": {"id": cluster.id, "code": cluster.code, "name": cluster.name},
        "address": school.address,
        "school_type": school.school_type,
        "medium": school.medium,
        "contact_phone": school.contact_phone,
        "contact_email": school.contact_email,
        "contact_teacher": (
            {"teacher_id": contact.teacher_id, "name": contact_user.name, "since": contact.start_date}
            if contact
            else None
        ),
        "custom": school.custom or {},
        "status": school.status,
        "version": school.version,
    }


def _school_fields(school: School) -> dict[str, Any]:
    return {
        "cluster_id": school.cluster_id,
        "code": school.code,
        "name": school.name,
        "address": school.address,
        "school_type": school.school_type,
        "medium": school.medium,
        "contact_phone": school.contact_phone,
        "contact_email": school.contact_email,
        "custom": school.custom or {},
        "status": school.status,
    }


def get_school(db: Session, principal: Principal, school_id: int, *, write: bool = False) -> School:
    school = db.get(School, school_id)
    if school is None:
        raise not_found()
    if principal.role == Role.SUPERVISOR and not write:
        # Supervisors may read schools they are or were assigned to.
        supervisor = assignment_queries.supervisor_for_user(db, principal.user.id)
        if supervisor is None or school.id not in assignment_queries.school_ids_for_supervisor(db, supervisor.id):
            deny(db, "school", school_id)
        return school
    ensure_cluster_in_scope(db, principal, school.cluster_id, entity="school", entity_id=school_id)
    return school


def list_schools(
    db: Session,
    principal: Principal,
    *,
    q: str | None = None,
    status: str | None = None,
    cluster_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    query = select(School, Cluster).join(Cluster, Cluster.id == School.cluster_id).order_by(School.code)
    if principal.role == Role.SUPERVISOR:
        # A supervisor's list is the schools assigned to them today.
        supervisor = assignment_queries.supervisor_for_user(db, principal.user.id)
        today = clock.local_date(get_district(db).time_zone)
        ids = assignment_queries.school_ids_for_supervisor(db, supervisor.id, today) if supervisor else set()
        query = query.where(School.id.in_(ids))
    else:
        allowed = managed_cluster_ids(db, principal)
        if allowed is not None:
            query = query.where(School.cluster_id.in_(allowed))
    if q:
        pattern = like_pattern(q)
        query = query.where(School.name_search.like(pattern) | School.code.like(f"%{q.strip()}%"))
    if status:
        query = query.where(School.status == status)
    if cluster_id:
        query = query.where(School.cluster_id == cluster_id)
    rows, total = paginate(db, query, page, page_size)
    return {"items": [school_out(db, s, c) for s, c in rows], "total": total, "page": page}


def _ensure_cluster_usable(db: Session, principal: Principal, cluster_id: int) -> Cluster:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise invalid("cluster_unknown")
    allowed = managed_cluster_ids(db, principal)
    if allowed is not None and cluster.id not in allowed:
        deny(db, "cluster", cluster_id)
    if cluster.status != EntityStatus.ACTIVE:
        raise invalid("cluster_inactive")
    return cluster


def create_school(db: Session, principal: Principal, body: SchoolIn, *, commit: bool = True) -> School:
    cluster = _ensure_cluster_usable(db, principal, body.cluster_id)
    if db.execute(select(School.id).where(School.code == body.code)).first():
        raise AppError(409, "code_taken")
    school = School(
        cluster_id=cluster.id,
        code=body.code,
        name=body.name,
        name_search=fold_search(body.name),
        address=body.address,
        school_type=body.school_type,
        medium=body.medium,
        contact_phone=body.contact_phone,
        contact_email=body.contact_email,
        custom=validate_custom(db, "school", body.custom),
    )
    db.add(school)
    db.flush()
    audit.record(
        db,
        "school.created",
        entity_type="school",
        entity_id=school.id,
        cluster_id=cluster.id,
        after=_school_fields(school),
    )
    if commit:
        db.commit()
    return school


def update_school(
    db: Session, principal: Principal, school_id: int, body: SchoolUpdate, *, commit: bool = True
) -> School:
    school = get_school(db, principal, school_id, write=True)
    check_version(body.version, school.version, school_out(db, school))
    before = _school_fields(school)
    for field in ("name", "address", "school_type", "medium", "contact_phone"):
        value = getattr(body, field)
        if value is not None:
            setattr(school, field, value)
    if "contact_email" in body.model_fields_set:
        school.contact_email = body.contact_email
    if body.custom is not None:
        school.custom = validate_custom(db, "school", body.custom, school.custom)
    school.name_search = fold_search(school.name)
    old, new = audit.changed_fields(before, _school_fields(school))
    if new:
        db.flush()
        audit.record(
            db,
            "school.updated",
            entity_type="school",
            entity_id=school.id,
            cluster_id=school.cluster_id,
            before=old,
            after=new,
        )
    if commit:
        db.commit()
    return school


def set_school_status(db: Session, principal: Principal, school_id: int, status: EntityStatus) -> School:
    school = get_school(db, principal, school_id, write=True)
    if status == EntityStatus.ACTIVE:
        _ensure_cluster_usable(db, principal, school.cluster_id)
    else:
        # FR-S7: end or move the school's assignments first.
        today = clock.local_date(get_district(db).time_zone)
        open_assignments = assignment_queries.open_count(db, today, school_id=school.id)
        if open_assignments:
            raise AppError(409, "school_has_assignments", {"count": open_assignments})
    school.status = status
    db.flush()
    audit.record(
        db,
        f"school.{'deactivated' if status == EntityStatus.INACTIVE else 'reactivated'}",
        entity_type="school",
        entity_id=school.id,
        cluster_id=school.cluster_id,
    )
    db.commit()
    return school


# Contact teachers -------------------------------------------------------------


def current_contact(db: Session, school_id: int) -> SchoolContact | None:
    return db.execute(
        select(SchoolContact).where(SchoolContact.school_id == school_id, SchoolContact.end_date.is_(None))
    ).scalar_one_or_none()


def end_contact(db: Session, school_id: int, reason: str) -> None:
    contact = current_contact(db, school_id)
    if contact is None:
        return
    contact.end_date = clock.local_date(get_district(db).time_zone)
    audit.record(
        db,
        "school.contact_ended",
        entity_type="school",
        entity_id=school_id,
        before={"teacher_id": contact.teacher_id},
        after={"reason": reason},
    )


def set_contact_teacher(db: Session, principal: Principal, school_id: int, teacher_id: int) -> School:
    """Designate the school's contact teacher (FR-S6). One at a time."""
    school = get_school(db, principal, school_id, write=True)
    teacher = db.get(Teacher, teacher_id)
    if teacher is None or teacher.school_id != school.id or teacher.status != EntityStatus.ACTIVE:
        raise invalid("teacher_not_at_school")
    previous = current_contact(db, school.id)
    if previous and previous.teacher_id == teacher.id:
        return school
    today = clock.local_date(get_district(db).time_zone)
    if previous:
        previous.end_date = today
    db.add(SchoolContact(school_id=school.id, teacher_id=teacher.id, start_date=today, created_by=principal.user.id))
    db.flush()
    audit.record(
        db,
        "school.contact_changed",
        entity_type="school",
        entity_id=school.id,
        cluster_id=school.cluster_id,
        before={"teacher_id": previous.teacher_id if previous else None},
        after={"teacher_id": teacher.id},
    )
    # FR-S6: open requests addressed to the school's contact follow the new one.
    from app.requests import service as requests

    requests.on_contact_changed(db, school.id, teacher.id)
    db.commit()
    return school


def school_contact_history(db: Session, principal: Principal, school_id: int) -> list[dict[str, Any]]:
    get_school(db, principal, school_id)
    rows = db.execute(
        select(SchoolContact, User)
        .join(Teacher, Teacher.id == SchoolContact.teacher_id)
        .join(User, User.id == Teacher.user_id)
        .where(SchoolContact.school_id == school_id)
        .order_by(SchoolContact.start_date.desc(), SchoolContact.id.desc())
    ).all()
    return [
        {"teacher_id": c.teacher_id, "name": u.name, "start_date": c.start_date, "end_date": c.end_date}
        for c, u in rows
    ]
