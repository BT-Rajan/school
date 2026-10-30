"""User accounts, teachers and supervisors (section 6)."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import clock
from app.assignments import queries as assignment_queries
from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import Principal
from app.db import preload
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.mail import queue as mail
from app.models import (
    Cluster,
    EntityStatus,
    Invitation,
    ReferenceValue,
    Role,
    School,
    Supervisor,
    SupervisorClusterMove,
    Teacher,
    TeacherClass,
    TeacherQualification,
    TeacherSubject,
    TeacherTransfer,
    User,
    UserStatus,
)

from .common import (
    check_version,
    deny,
    ensure_cluster_in_scope,
    fold_search,
    like_pattern,
    managed_cluster_ids,
    resolve_reference,
    validate_custom,
)
from .schemas import PersonUpdate, StaffIn, SupervisorIn, TeacherIn, TeacherUpdate, TransferIn
from .service import current_contact, end_contact, paginate

# Accounts -------------------------------------------------------------------------


def user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "role": user.role,
        "staff_id": user.staff_id,
        "name": user.name,
        "email": user.email,
        "locale": user.locale,
        "status": user.status,
        "mfa_method": user.mfa_method,
        "locked": user.is_locked(),
        "last_login_at": user.last_login_at,
        "version": user.version,
    }


def create_user(
    db: Session,
    *,
    role: Role,
    name: str,
    email: str,
    staff_id: str | None,
    locale: str | None,
    created_by: int | None,
    send_at: datetime | None = None,
    invite: bool = True,
) -> User:
    email = auth.normalize_email(email)
    if db.execute(select(User.id).where(User.email == email)).first():
        raise AppError(409, "email_taken")
    if staff_id and db.execute(select(User.id).where(User.staff_id == staff_id)).first():
        raise AppError(409, "staff_id_taken")
    user = User(
        role=role,
        name=name.strip(),
        name_search=fold_search(name),
        email=email,
        staff_id=staff_id,
        locale=locale or get_district(db).default_locale,
        status=UserStatus.INVITED,
    )
    db.add(user)
    db.flush()
    audit.record(db, "user.created", entity_type="user", entity_id=user.id, after={"role": role, "staff_id": staff_id})
    if invite:
        auth.create_invitation(db, user, created_by, send_at=send_at)
    return user


def create_staff(db: Session, principal: Principal, role: Role, body: StaffIn) -> User:
    user = create_user(
        db,
        role=role,
        name=body.name,
        email=body.email,
        staff_id=body.staff_id,
        locale=body.locale,
        created_by=principal.user.id,
    )
    db.commit()
    return user


def list_users(db: Session, role: Role) -> list[dict[str, Any]]:
    users = db.execute(select(User).where(User.role == role).order_by(User.name)).scalars()
    return [user_out(u) for u in users]


def _cluster_of(db: Session, user: User) -> int | None:
    if user.role == Role.TEACHER:
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one()
        return db.get(School, teacher.school_id).cluster_id
    if user.role == Role.SUPERVISOR:
        return db.execute(select(Supervisor.cluster_id).where(Supervisor.user_id == user.id)).scalar_one()
    return None


def get_managed_user(db: Session, principal: Principal, user_id: int) -> User:
    """A user the principal may manage. Cluster Heads manage their cluster's teachers and supervisors."""
    user = db.get(User, user_id)
    if user is None:
        raise not_found()
    if principal.role == Role.DISTRICT_ADMIN:
        return user
    if principal.role == Role.CLUSTER_HEAD and user.role in (Role.TEACHER, Role.SUPERVISOR):
        ensure_cluster_in_scope(db, principal, _cluster_of(db, user), entity="user", entity_id=user_id)
        return user
    deny(db, "user", user_id)
    raise AssertionError  # deny always raises


def _update_account(db: Session, user: User, name: str | None, email: str | None) -> None:
    if name is not None:
        user.name = name.strip()
        user.name_search = fold_search(name)
    if email is not None:
        email = auth.normalize_email(email)
        if email != user.email:
            if user.status != UserStatus.INVITED:
                # A verified address only changes through a new invitation by an admin.
                raise invalid("email_locked")
            if db.execute(select(User.id).where(User.email == email, User.id != user.id)).first():
                raise AppError(409, "email_taken")
            user.email = email


def resend_invitation(db: Session, principal: Principal, user_id: int) -> None:
    user = get_managed_user(db, principal, user_id)
    if user.status != UserStatus.INVITED:
        raise invalid("not_invited")
    auth.create_invitation(db, user, principal.user.id)
    db.commit()


def deactivate_user(db: Session, principal: Principal, user_id: int) -> User:
    user = get_managed_user(db, principal, user_id)
    if user.status == UserStatus.INACTIVE:
        return user
    if user.role == Role.DISTRICT_ADMIN:
        others = db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.DISTRICT_ADMIN, User.status == UserStatus.ACTIVE, User.id != user.id)
        ).scalar_one()
        if others < 2:
            # FR-AD5: at least two active admins must remain.
            raise AppError(409, "last_admins")
    if user.role == Role.CLUSTER_HEAD:
        headed = db.execute(
            select(func.count())
            .select_from(Cluster)
            .where(Cluster.cluster_head_id == user.id, Cluster.status == EntityStatus.ACTIVE)
        ).scalar_one()
        if headed:
            raise AppError(409, "cluster_head_has_clusters", {"count": headed})
    if user.role == Role.TEACHER:
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one()
        teacher.status = EntityStatus.INACTIVE
        _end_contact_if_teacher(db, teacher, "teacher_deactivated")
    if user.role == Role.SUPERVISOR:
        # FR-P3: blocked while the supervisor has current or upcoming assignments.
        supervisor = db.execute(select(Supervisor).where(Supervisor.user_id == user.id)).scalar_one()
        today = clock.local_date(get_district(db).time_zone)
        open_assignments = assignment_queries.open_count(db, today, supervisor_id=supervisor.id)
        if open_assignments:
            raise AppError(409, "supervisor_has_assignments", {"count": open_assignments})
        db.execute(update(Supervisor).where(Supervisor.user_id == user.id).values(status=EntityStatus.INACTIVE))
    user.status = UserStatus.INACTIVE
    auth.revoke_sessions(db, user.id, "deactivated")
    db.execute(
        update(Invitation)
        .where(Invitation.user_id == user.id, Invitation.used_at.is_(None), Invitation.revoked_at.is_(None))
        .values(revoked_at=clock.now())
    )
    db.flush()
    audit.record(db, "user.deactivated", entity_type="user", entity_id=user.id, cluster_id=_cluster_of(db, user))
    db.commit()
    return user


def reactivate_user(db: Session, principal: Principal, user_id: int) -> User:
    user = get_managed_user(db, principal, user_id)
    if user.status != UserStatus.INACTIVE:
        return user
    if user.role == Role.TEACHER:
        db.execute(update(Teacher).where(Teacher.user_id == user.id).values(status=EntityStatus.ACTIVE))
    if user.role == Role.SUPERVISOR:
        db.execute(update(Supervisor).where(Supervisor.user_id == user.id).values(status=EntityStatus.ACTIVE))
    if user.password_hash:
        user.status = UserStatus.ACTIVE
    else:
        user.status = UserStatus.INVITED
        auth.create_invitation(db, user, principal.user.id)
    db.flush()
    audit.record(db, "user.reactivated", entity_type="user", entity_id=user.id, cluster_id=_cluster_of(db, user))
    db.commit()
    return user


# Teachers ---------------------------------------------------------------------------


def _end_contact_if_teacher(db: Session, teacher: Teacher, reason: str) -> None:
    contact = current_contact(db, teacher.school_id)
    if contact and contact.teacher_id == teacher.id:
        end_contact(db, teacher.school_id, reason)


def _reference_map(db: Session) -> dict[int, ReferenceValue]:
    return {r.id: r for r in db.execute(select(ReferenceValue)).scalars()}


def _ref_out(ref: ReferenceValue) -> dict[str, Any]:
    return {"code": ref.code, "name_en": ref.name_en, "name_ar": ref.name_ar}


def teacher_out(
    db: Session,
    teacher: Teacher,
    user: User | None = None,
    refs: dict | None = None,
    links: dict[int, dict[str, list]] | None = None,
) -> dict[str, Any]:
    user = user or db.get(User, teacher.user_id)
    refs = refs or _reference_map(db)
    school = db.get(School, teacher.school_id)
    cluster = db.get(Cluster, school.cluster_id)
    own = (links or _teacher_links(db, [teacher.id]))[teacher.id]
    subjects, classes, quals = own["subjects"], own["classes"], own["quals"]
    today = clock.local_date(get_district(db).time_zone)
    return {
        "id": teacher.id,
        "user_id": user.id,
        "staff_id": user.staff_id,
        "name": user.name,
        "email": user.email,
        "account_status": user.status,
        "status": teacher.status,
        "district": get_district(db).code,
        "cluster": {"id": cluster.id, "code": cluster.code, "name": cluster.name},
        "school": {"id": school.id, "code": school.code, "name": school.name},
        "designation": _ref_out(refs[teacher.designation_id]),
        "subjects": sorted((_ref_out(refs[i]) for i in subjects), key=lambda r: r["code"]),
        "classes": sorted((_ref_out(refs[i]) for i in classes), key=lambda r: r["code"]),
        "experience_years": teacher.current_experience(today),
        "experience_recorded": {"years": teacher.experience_years, "as_of": teacher.experience_as_of},
        "qualifications": sorted(
            ({**_ref_out(refs[q.reference_value_id]), "year": q.year} for q in quals), key=lambda r: r["code"]
        ),
        "custom": teacher.custom or {},
        "version": teacher.version,
    }


def _teacher_links(db: Session, ids: list[int]) -> dict[int, dict[str, list]]:
    """Subjects, classes and qualifications of these teachers, three queries for a whole page."""
    links: dict[int, dict[str, list]] = {i: {"subjects": [], "classes": [], "quals": []} for i in ids}
    if not ids:
        return links
    for tid, ref in db.execute(
        select(TeacherSubject.teacher_id, TeacherSubject.reference_value_id).where(TeacherSubject.teacher_id.in_(ids))
    ):
        links[tid]["subjects"].append(ref)
    for tid, ref in db.execute(
        select(TeacherClass.teacher_id, TeacherClass.reference_value_id).where(TeacherClass.teacher_id.in_(ids))
    ):
        links[tid]["classes"].append(ref)
    for q in db.execute(select(TeacherQualification).where(TeacherQualification.teacher_id.in_(ids))).scalars():
        links[q.teacher_id]["quals"].append(q)
    return links


def _teacher_fields(db: Session, teacher: Teacher, user: User) -> dict[str, Any]:
    """Identifiers and values for audit entries (FR-L6)."""
    return {
        "staff_id": user.staff_id,
        "school_id": teacher.school_id,
        "designation_id": teacher.designation_id,
        "subjects": sorted(
            db.execute(
                select(TeacherSubject.reference_value_id).where(TeacherSubject.teacher_id == teacher.id)
            ).scalars()
        ),
        "classes": sorted(
            db.execute(select(TeacherClass.reference_value_id).where(TeacherClass.teacher_id == teacher.id)).scalars()
        ),
        "qualifications": sorted(
            (q.reference_value_id, q.year)
            for q in db.execute(
                select(TeacherQualification).where(TeacherQualification.teacher_id == teacher.id)
            ).scalars()
        ),
        "experience_years": teacher.experience_years,
        "experience_as_of": teacher.experience_as_of,
        "custom": teacher.custom or {},
        "name": user.name,
        "email": user.email,
    }


def _usable_school(db: Session, principal: Principal, school_id: int) -> School:
    school = db.get(School, school_id)
    if school is None:
        raise invalid("school_unknown")
    allowed = managed_cluster_ids(db, principal)
    if allowed is not None and school.cluster_id not in allowed:
        deny(db, "school", school_id)
    if school.status != EntityStatus.ACTIVE:
        raise invalid("school_inactive")
    return school


def _set_teacher_lists(db: Session, teacher: Teacher, subjects, classes, qualifications) -> None:
    if subjects is not None:
        ids = {resolve_reference(db, "subject", code, "subjects").id for code in subjects}
        db.query(TeacherSubject).filter(TeacherSubject.teacher_id == teacher.id).delete()
        db.add_all(TeacherSubject(teacher_id=teacher.id, reference_value_id=i) for i in ids)
    if classes is not None:
        ids = {resolve_reference(db, "class", code, "classes").id for code in classes}
        db.query(TeacherClass).filter(TeacherClass.teacher_id == teacher.id).delete()
        db.add_all(TeacherClass(teacher_id=teacher.id, reference_value_id=i) for i in ids)
    if qualifications is not None:
        by_id: dict[int, int | None] = {}
        for qual in qualifications:
            by_id[resolve_reference(db, "qualification", qual.code, "qualifications").id] = qual.year
        db.query(TeacherQualification).filter(TeacherQualification.teacher_id == teacher.id).delete()
        db.add_all(TeacherQualification(teacher_id=teacher.id, reference_value_id=i, year=y) for i, y in by_id.items())
    db.flush()


def create_teacher(
    db: Session, principal: Principal, body: TeacherIn, *, send_at: datetime | None = None, commit: bool = True
) -> Teacher:
    school = _usable_school(db, principal, body.school_id)
    designation = resolve_reference(db, "designation", body.designation, "designation")
    custom = validate_custom(db, "teacher", body.custom)
    user = create_user(
        db,
        role=Role.TEACHER,
        name=body.name,
        email=body.email,
        staff_id=body.staff_id,
        locale=body.locale,
        created_by=principal.user.id,
        send_at=send_at,
    )
    teacher = Teacher(
        user_id=user.id,
        school_id=school.id,
        designation_id=designation.id,
        experience_years=body.experience_years,
        experience_as_of=body.experience_as_of or clock.local_date(get_district(db).time_zone),
        custom=custom,
    )
    db.add(teacher)
    db.flush()
    _set_teacher_lists(db, teacher, body.subjects, body.classes, body.qualifications)
    audit.record(
        db,
        "teacher.created",
        entity_type="teacher",
        entity_id=teacher.id,
        cluster_id=school.cluster_id,
        after=_teacher_fields(db, teacher, user),
    )
    if commit:
        db.commit()
    return teacher


def _supervisor_school_ids(db: Session, principal: Principal) -> set[int]:
    """Supervisors see the teachers of the schools assigned to them today."""
    supervisor = assignment_queries.supervisor_for_user(db, principal.user.id)
    if supervisor is None:
        return set()
    return assignment_queries.school_ids_for_supervisor(db, supervisor.id, clock.local_date(get_district(db).time_zone))


def get_teacher(db: Session, principal: Principal, teacher_id: int) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise not_found()
    if principal.role == Role.TEACHER and teacher.user_id == principal.user.id:
        return teacher
    if principal.role == Role.SUPERVISOR:
        if teacher.school_id not in _supervisor_school_ids(db, principal):
            deny(db, "teacher", teacher_id)
        return teacher
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
        deny(db, "teacher", teacher_id)
    school = db.get(School, teacher.school_id)
    ensure_cluster_in_scope(db, principal, school.cluster_id, entity="teacher", entity_id=teacher_id)
    return teacher


def update_teacher(
    db: Session, principal: Principal, teacher_id: int, body: TeacherUpdate, *, commit: bool = True
) -> Teacher:
    teacher = get_teacher(db, principal, teacher_id)
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
        deny(db, "teacher", teacher_id)
    user = db.get(User, teacher.user_id)
    check_version(body.version, teacher.version, teacher_out(db, teacher, user))
    before = _teacher_fields(db, teacher, user)
    _update_account(db, user, body.name, body.email)
    if body.designation is not None:
        teacher.designation_id = resolve_reference(db, "designation", body.designation, "designation").id
    if body.experience_years is not None:
        teacher.experience_years = body.experience_years
        teacher.experience_as_of = body.experience_as_of or clock.local_date(get_district(db).time_zone)
    if body.custom is not None:
        teacher.custom = validate_custom(db, "teacher", body.custom, teacher.custom)
    _set_teacher_lists(db, teacher, body.subjects, body.classes, body.qualifications)
    after = _teacher_fields(db, teacher, user)
    old, new = audit.changed_fields(before, after)
    if new:
        # Lists live in other tables, so bump the version explicitly.
        teacher.updated_at = clock.now()
        db.flush()
        audit.record(
            db,
            "teacher.updated",
            entity_type="teacher",
            entity_id=teacher.id,
            cluster_id=db.get(School, teacher.school_id).cluster_id,
            before=old,
            after=new,
        )
    if commit:
        db.commit()
    return teacher


def transfer_teacher(db: Session, principal: Principal, teacher_id: int, body: TransferIn) -> Teacher:
    """Move a teacher to another school in the same cluster (FR-T3)."""
    teacher = get_teacher(db, principal, teacher_id)
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
        deny(db, "teacher", teacher_id)
    if teacher.status != EntityStatus.ACTIVE:
        raise invalid("teacher_inactive")
    source = db.get(School, teacher.school_id)
    target = _usable_school(db, principal, body.school_id)
    if target.id == source.id:
        raise invalid("same_school")
    if target.cluster_id != source.cluster_id:
        raise invalid("transfer_across_clusters")
    moved_on = body.moved_on or clock.local_date(get_district(db).time_zone)
    _end_contact_if_teacher(db, teacher, "teacher_transferred")
    teacher.school_id = target.id
    db.add(
        TeacherTransfer(
            teacher_id=teacher.id,
            from_school_id=source.id,
            to_school_id=target.id,
            moved_on=moved_on,
            moved_by=principal.user.id,
        )
    )
    db.flush()
    audit.record(
        db,
        "teacher.transferred",
        entity_type="teacher",
        entity_id=teacher.id,
        cluster_id=source.cluster_id,
        before={"school_id": source.id},
        after={"school_id": target.id, "moved_on": moved_on},
    )
    db.commit()
    return teacher


def teacher_transfers(db: Session, principal: Principal, teacher_id: int) -> list[dict[str, Any]]:
    get_teacher(db, principal, teacher_id)
    rows = db.execute(
        select(TeacherTransfer).where(TeacherTransfer.teacher_id == teacher_id).order_by(TeacherTransfer.id.desc())
    ).scalars()
    return [
        {
            "from_school_id": t.from_school_id,
            "to_school_id": t.to_school_id,
            "moved_on": t.moved_on,
            "moved_by": t.moved_by,
        }
        for t in rows
    ]


def list_teachers(
    db: Session,
    principal: Principal,
    *,
    q: str | None = None,
    status: str | None = None,
    school_id: int | None = None,
    cluster_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR):
        deny(db, "teacher", None)
    query = (
        select(Teacher, User)
        .join(User, User.id == Teacher.user_id)
        .join(School, School.id == Teacher.school_id)
        .order_by(User.name_search, Teacher.id)
    )
    if principal.role == Role.SUPERVISOR:
        query = query.where(Teacher.school_id.in_(_supervisor_school_ids(db, principal)))
    else:
        allowed = managed_cluster_ids(db, principal)
        if allowed is not None:
            query = query.where(School.cluster_id.in_(allowed))
    if q:
        query = query.where(User.name_search.like(like_pattern(q)) | User.staff_id.like(f"%{q.strip()}%"))
    if status:
        query = query.where(Teacher.status == status)
    if school_id:
        query = query.where(Teacher.school_id == school_id)
    if cluster_id:
        query = query.where(School.cluster_id == cluster_id)
    rows, total = paginate(db, query, page, page_size)
    refs = _reference_map(db)
    preload(db, School, {t.school_id for t, _ in rows})
    preload(db, Cluster, {db.get(School, t.school_id).cluster_id for t, _ in rows})
    links = _teacher_links(db, [t.id for t, _ in rows])
    return {"items": [teacher_out(db, t, u, refs, links) for t, u in rows], "total": total, "page": page}


# Supervisors ----------------------------------------------------------------------


def supervisor_out(db: Session, supervisor: Supervisor, user: User | None = None) -> dict[str, Any]:
    user = user or db.get(User, supervisor.user_id)
    cluster = db.get(Cluster, supervisor.cluster_id)
    return {
        "id": supervisor.id,
        "user_id": user.id,
        "staff_id": user.staff_id,
        "name": user.name,
        "email": user.email,
        "account_status": user.status,
        "status": supervisor.status,
        "cluster": {"id": cluster.id, "code": cluster.code, "name": cluster.name},
        # Assignment, evaluation and report counts are added with Phase 2 (FR-P4).
        "version": supervisor.version,
    }


def _usable_cluster(db: Session, principal: Principal, cluster_id: int) -> Cluster:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise invalid("cluster_unknown")
    allowed = managed_cluster_ids(db, principal)
    if allowed is not None and cluster.id not in allowed:
        deny(db, "cluster", cluster_id)
    if cluster.status != EntityStatus.ACTIVE:
        raise invalid("cluster_inactive")
    return cluster


def create_supervisor(
    db: Session, principal: Principal, body: SupervisorIn, *, send_at: datetime | None = None, commit: bool = True
) -> Supervisor:
    cluster = _usable_cluster(db, principal, body.cluster_id)
    user = create_user(
        db,
        role=Role.SUPERVISOR,
        name=body.name,
        email=body.email,
        staff_id=body.staff_id,
        locale=body.locale,
        created_by=principal.user.id,
        send_at=send_at,
    )
    supervisor = Supervisor(user_id=user.id, cluster_id=cluster.id)
    db.add(supervisor)
    db.flush()
    audit.record(
        db,
        "supervisor.created",
        entity_type="supervisor",
        entity_id=supervisor.id,
        cluster_id=cluster.id,
        after={"user_id": user.id, "staff_id": user.staff_id},
    )
    if commit:
        db.commit()
    return supervisor


def get_supervisor(db: Session, principal: Principal, supervisor_id: int) -> Supervisor:
    supervisor = db.get(Supervisor, supervisor_id)
    if supervisor is None:
        raise not_found()
    if principal.role == Role.SUPERVISOR and supervisor.user_id == principal.user.id:
        return supervisor
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
        deny(db, "supervisor", supervisor_id)
    ensure_cluster_in_scope(db, principal, supervisor.cluster_id, entity="supervisor", entity_id=supervisor_id)
    return supervisor


def update_supervisor(
    db: Session, principal: Principal, supervisor_id: int, body: PersonUpdate, *, commit: bool = True
) -> Supervisor:
    supervisor = get_supervisor(db, principal, supervisor_id)
    if principal.role == Role.SUPERVISOR:
        deny(db, "supervisor", supervisor_id)
    user = db.get(User, supervisor.user_id)
    check_version(body.version, supervisor.version, supervisor_out(db, supervisor, user))
    before = {"name": user.name, "email": user.email}
    _update_account(db, user, body.name, body.email)
    old, new = audit.changed_fields(before, {"name": user.name, "email": user.email})
    if new:
        supervisor.updated_at = clock.now()
        db.flush()
        audit.record(
            db,
            "supervisor.updated",
            entity_type="supervisor",
            entity_id=supervisor.id,
            cluster_id=supervisor.cluster_id,
            before=old,
            after=new,
        )
    if commit:
        db.commit()
    return supervisor


def move_supervisor(db: Session, principal: Principal, supervisor_id: int, cluster_id: int) -> Supervisor:
    """Admin moves a supervisor to another cluster (FR-P5)."""
    supervisor = get_supervisor(db, principal, supervisor_id)
    target = _usable_cluster(db, principal, cluster_id)
    if target.id == supervisor.cluster_id:
        raise invalid("same_cluster")
    # FR-P5: the old cluster's assignments must end first.
    open_assignments = assignment_queries.open_count(
        db, clock.local_date(get_district(db).time_zone), supervisor_id=supervisor.id
    )
    if open_assignments:
        raise AppError(409, "supervisor_has_assignments", {"count": open_assignments})
    source_id = supervisor.cluster_id
    supervisor.cluster_id = target.id
    db.add(
        SupervisorClusterMove(
            supervisor_id=supervisor.id, from_cluster_id=source_id, to_cluster_id=target.id, moved_by=principal.user.id
        )
    )
    db.flush()
    audit.record(
        db,
        "supervisor.moved",
        entity_type="supervisor",
        entity_id=supervisor.id,
        cluster_id=source_id,
        before={"cluster_id": source_id},
        after={"cluster_id": target.id},
    )
    db.commit()
    return supervisor


def list_supervisors(
    db: Session,
    principal: Principal,
    *,
    q: str | None = None,
    status: str | None = None,
    cluster_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
        deny(db, "supervisor", None)
    query = select(Supervisor, User).join(User, User.id == Supervisor.user_id).order_by(User.name_search, Supervisor.id)
    allowed = managed_cluster_ids(db, principal)
    if allowed is not None:
        query = query.where(Supervisor.cluster_id.in_(allowed))
    if q:
        query = query.where(User.name_search.like(like_pattern(q)) | User.staff_id.like(f"%{q.strip()}%"))
    if status:
        query = query.where(Supervisor.status == status)
    if cluster_id:
        query = query.where(Supervisor.cluster_id == cluster_id)
    rows, total = paginate(db, query, page, page_size)
    return {"items": [supervisor_out(db, s, u) for s, u in rows], "total": total, "page": page}


def update_staff(db: Session, user_id: int, body: PersonUpdate) -> User:
    """Admin edits a District Admin or Cluster Head account."""
    user = db.get(User, user_id)
    if user is None or user.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
        raise not_found()
    check_version(body.version, user.version, user_out(user))
    before = {"name": user.name, "email": user.email}
    _update_account(db, user, body.name, body.email)
    old, new = audit.changed_fields(before, {"name": user.name, "email": user.email})
    if new:
        db.flush()
        audit.record(db, "user.updated", entity_type="user", entity_id=user.id, before=old, after=new)
    db.commit()
    return user


# Teacher onboarding at scale (Phase 3) --------------------------------------------------------


def _teacher_users_in_scope(db: Session, principal: Principal, cluster_id: int | None):
    allowed = managed_cluster_ids(db, principal)
    if cluster_id is not None:
        ensure_cluster_in_scope(db, principal, cluster_id, entity="cluster", entity_id=cluster_id)
    query = (
        select(User)
        .join(Teacher, Teacher.user_id == User.id)
        .join(School, School.id == Teacher.school_id)
        .where(Teacher.status == EntityStatus.ACTIVE)
    )
    if cluster_id is not None:
        query = query.where(School.cluster_id == cluster_id)
    elif allowed is not None:
        query = query.where(School.cluster_id.in_(allowed))
    return list(db.execute(query.order_by(User.id)).scalars())


def _waiting_invitation(db: Session, user_id: int) -> Invitation | None:
    return db.execute(
        select(Invitation).where(
            Invitation.user_id == user_id,
            Invitation.used_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > clock.now(),
        )
    ).scalar_one_or_none()


def onboarding_status(db: Session, principal: Principal, cluster_id: int | None = None) -> dict[str, Any]:
    """How many teachers have joined, have a live invitation, or need one."""
    counts = {"active": 0, "invited": 0, "needs_invitation": 0}
    for user in _teacher_users_in_scope(db, principal, cluster_id):
        if user.status == UserStatus.ACTIVE:
            counts["active"] += 1
        elif user.status == UserStatus.INVITED:
            counts["invited" if _waiting_invitation(db, user.id) else "needs_invitation"] += 1
    return counts


def invite_waiting_teachers(db: Session, principal: Principal, cluster_id: int | None = None) -> dict[str, Any]:
    """Invite every teacher who has not joined and has no live invitation, within the
    daily invitation cap, so sign-in codes keep their reserved mail budget (FR-N8)."""
    users = [
        u
        for u in _teacher_users_in_scope(db, principal, cluster_id)
        if u.status == UserStatus.INVITED and _waiting_invitation(db, u.id) is None
    ]
    times = mail.invitation_send_times(db, len(users))
    district = get_district(db)
    per_day: dict[str, int] = {}
    for user, at in zip(users, times, strict=True):
        auth.create_invitation(db, user, principal.user.id, send_at=at)
        day = clock.local_date(district.time_zone, at).isoformat()
        per_day[day] = per_day.get(day, 0) + 1
    audit.record(
        db,
        "teachers.invited",
        entity_type="cluster",
        entity_id=cluster_id,
        after={"count": len(users), "by_day": per_day},
    )
    db.commit()
    return {"queued": len(users), "by_day": [{"date": d, "count": n} for d, n in sorted(per_day.items())]}
