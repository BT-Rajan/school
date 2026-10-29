"""School and Teacher evaluations, supervisor sections (section 8.4).

Teacher sections arrive in Phase 3; until then an evaluation holds only the
form's supervisor sections, and submission needs only those.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.assignments import queries as assignments
from app.audit import service as audit
from app.auth.deps import Principal
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.files import service as files
from app.forms import schema as form_schema
from app.models import (
    Cluster,
    Evaluation,
    EvaluationAmendment,
    EvaluationSection,
    FormVersion,
    MinistryReport,
    MinistryReportVersion,
    Role,
    School,
    StoredFile,
    Supervisor,
    Teacher,
    User,
)
from app.notifications import service as notify
from app.requests import service as requests
from app.structure.common import deny, managed_cluster_ids
from app.structure.service import paginate

EDITABLE = ("draft",)


class StartIn(BaseModel):
    form_id: int
    school_id: int
    teacher_id: int | None = None
    visit_date: date | None = None
    client_key: str | None = Field(default=None, max_length=64)


class SaveIn(BaseModel):
    version: int
    visit_date: date | None = None
    visit_notes: str | None = Field(default=None, max_length=10000)
    sections: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Location(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: int | None = Field(default=None, ge=0, le=100000)


class SubmitIn(BaseModel):
    version: int
    location: Location | None = None
    # When the supervisor pressed Submit, possibly offline (FR-PW11).
    device_time: datetime | None = None

    @field_validator("device_time")
    @classmethod
    def _naive_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC).replace(tzinfo=None) if value and value.tzinfo else value


class AmendIn(SaveIn):
    reason: str = Field(min_length=1, max_length=1000)


class CancelIn(BaseModel):
    version: int
    reason: str = Field(min_length=1, max_length=500)


def _today(db: Session) -> date:
    return clock.local_date(get_district(db).time_zone)


def _own_supervisor(db: Session, principal: Principal) -> Supervisor:
    if principal.role != Role.SUPERVISOR:
        raise AppError(403, "forbidden")
    supervisor = assignments.supervisor_for_user(db, principal.user.id)
    if supervisor is None:
        raise AppError(403, "forbidden")
    return supervisor


def _form_parts(db: Session, form: FormVersion) -> tuple[MinistryReportVersion, MinistryReport]:
    mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
    return mrv, db.get(MinistryReport, mrv.ministry_report_id)


# Access --------------------------------------------------------------------------------


def can_read(db: Session, principal: Principal, e: Evaluation) -> bool:
    """FR-E10: a supervisor sees only their own; Cluster Heads their cluster; admins everything."""
    if principal.role == Role.DISTRICT_ADMIN:
        return True
    if principal.role == Role.SUPERVISOR:
        own = assignments.supervisor_for_user(db, principal.user.id)
        return own is not None and own.id == e.supervisor_id
    if principal.role == Role.CLUSTER_HEAD:
        school = db.get(School, e.school_id)
        return school.cluster_id in (managed_cluster_ids(db, principal) or [])
    return False


def get_evaluation(db: Session, principal: Principal, evaluation_id: int) -> Evaluation:
    e = db.get(Evaluation, evaluation_id)
    if e is None:
        raise not_found()
    if not can_read(db, principal, e):
        deny(db, "evaluation", evaluation_id)
    return e


def _locked_own(db: Session, principal: Principal, evaluation_id: int, version: int) -> Evaluation:
    supervisor = _own_supervisor(db, principal)
    e = db.execute(
        select(Evaluation)
        .where(Evaluation.id == evaluation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if e is None or e.supervisor_id != supervisor.id:
        if e is not None:
            deny(db, "evaluation", evaluation_id)
        raise not_found()
    if e.version != version:
        raise AppError(409, "version_conflict", {"current": evaluation_out(db, e)})
    return e


def _evaluation_files_rule(db: Session, principal: Principal, file: StoredFile) -> bool:
    e = db.get(Evaluation, file.owner_id)
    return e is not None and can_read(db, principal, e)


files.register_owner("evaluation", _evaluation_files_rule)


# Output --------------------------------------------------------------------------------


def _sections(db: Session, e: Evaluation) -> list[EvaluationSection]:
    return list(
        db.execute(
            select(EvaluationSection).where(EvaluationSection.evaluation_id == e.id).order_by(EvaluationSection.id)
        ).scalars()
    )


def evaluation_out(db: Session, e: Evaluation, *, full: bool = True) -> dict[str, Any]:
    form = db.get(FormVersion, e.form_version_id)
    mrv, report = _form_parts(db, form)
    school = db.get(School, e.school_id)
    supervisor = db.get(Supervisor, e.supervisor_id)
    supervisor_user = db.get(User, supervisor.user_id)
    teacher_name = None
    if e.teacher_id:
        teacher = db.get(Teacher, e.teacher_id)
        teacher_name = db.get(User, teacher.user_id).name
    out: dict[str, Any] = {
        "id": e.id,
        "form_id": form.id,
        "report": {
            "code": report.report_code,
            "version_code": mrv.version_code,
            "title_en": mrv.title_en,
            "title_ar": mrv.title_ar,
        },
        "subject_type": e.subject_type,
        "school": {"id": school.id, "code": school.code, "name": school.name},
        "teacher": {"id": e.teacher_id, "name": teacher_name} if e.teacher_id else None,
        "supervisor": {"id": supervisor.id, "name": supervisor_user.name},
        "status": e.status,
        "visit_date": e.visit_date,
        "submitted_at": e.submitted_at,
        "amended_at": e.amended_at,
        "form_status": form.effective_status(_today(db)),
        "form_end_date": form.end_date,
        "version": e.version,
    }
    if full:
        out["visit_notes"] = e.visit_notes
        out["location"] = (
            {"latitude": float(e.latitude), "longitude": float(e.longitude), "accuracy_m": e.location_accuracy_m}
            if e.latitude is not None
            else None
        )
        out["cancel_reason"] = e.cancel_reason
        out["sections"] = [
            {
                "key": s.section_key,
                "respondent": s.respondent,
                "status": s.status,
                "answers": s.answers,
                "submitted_at": s.submitted_at,
            }
            for s in _sections(db, e)
        ] + requests.evaluation_sections(db, e)
        r = requests.evaluation_request(db, e)
        out["request"] = requests.summary(db, r) if r else None
    return out


# Rules ---------------------------------------------------------------------------------


def _notify_reviewers(db: Session, e: Evaluation, type_: str, **extra: Any) -> None:
    """FR-N2, FR-N7: admins get every evaluation; the Cluster Head gets their cluster's."""
    mrv, report = _form_parts(db, db.get(FormVersion, e.form_version_id))
    school = db.get(School, e.school_id)
    supervisor = db.get(Supervisor, e.supervisor_id)
    params = {
        "report_code": report.report_code,
        "version_code": mrv.version_code,
        "school": school.name,
        "supervisor": db.get(User, supervisor.user_id).name,
        "evaluation_id": e.id,
        **extra,
    }
    notify.notify_role(db, Role.DISTRICT_ADMIN, type_, params)
    head_id = db.get(Cluster, school.cluster_id).cluster_head_id
    if head_id:
        notify.notify(db, head_id, type_, params)


def _check_visit_date(db: Session, e: Evaluation, day: date | None) -> None:
    """FR-AS6: the visit date must fall inside one of the supervisor's windows for the school."""
    if day is None:
        return
    if day > _today(db):
        raise invalid("visit_date_in_future")
    if not assignments.date_in_window(db, e.supervisor_id, e.school_id, day):
        raise invalid("visit_date_outside_assignment")


def _file_checker(db: Session, principal: Principal, e: Evaluation):
    def ok(ids: list[int]) -> bool:
        for file_id in ids:
            file = db.get(StoredFile, file_id)
            if file is None or file.uploaded_by != principal.user.id or file.scan_status == "quarantined":
                return False
            if file.owner_type not in ("upload", "evaluation") or (
                file.owner_type == "evaluation" and file.owner_id != e.id
            ):
                return False
        return True

    return ok


def _claim_files(db: Session, e: Evaluation, answers: dict[str, Any], parsed: form_schema.FormSchema, key: str) -> None:
    section = next(s for s in parsed.sections if s.key == key)
    for q in section.questions:
        if q.type == "file":
            for file_id in answers.get(q.key) or []:
                file = db.get(StoredFile, file_id)
                file.owner_type, file.owner_id = "evaluation", e.id


def _apply_answers(
    db: Session, principal: Principal, e: Evaluation, sections: dict[str, dict[str, Any]], *, complete: bool
) -> None:
    form = db.get(FormVersion, e.form_version_id)
    parsed = form_schema.parse(form.schema)
    rows = {s.section_key: s for s in _sections(db, e)}
    problems: list[dict[str, str]] = []
    checker = _file_checker(db, principal, e)
    for key, answers in sections.items():
        row = rows.get(key)
        if row is None or row.respondent != "supervisor":
            problems.append({"where": key, "code": "section_not_yours"})
            continue
        cleaned, found = form_schema.validate_answers(parsed, key, answers, complete=False, file_ok=checker)
        problems += [{**p, "where": f"{key}.{p['where']}"} for p in found]
        if not found:
            row.answers = cleaned
            row.status = "in_progress" if row.status == "not_started" else row.status
            _claim_files(db, e, cleaned, parsed, key)
    if complete:
        for row in rows.values():
            if row.respondent != "supervisor":
                continue
            _, found = form_schema.validate_answers(
                parsed, row.section_key, row.answers, complete=True, file_ok=checker
            )
            problems += [{**p, "where": f"{row.section_key}.{p['where']}"} for p in found]
    if problems:
        raise invalid("answers_invalid", problems)


# Lifecycle -------------------------------------------------------------------------------


def start(db: Session, principal: Principal, body: StartIn) -> Evaluation:
    """FR-E4: from an assigned school or teacher, on an Active form."""
    supervisor = _own_supervisor(db, principal)
    if body.client_key:
        existing = db.execute(
            select(Evaluation).where(
                Evaluation.supervisor_id == supervisor.id, Evaluation.client_key == body.client_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    form = db.get(FormVersion, body.form_id)
    if form is None or form.status != "published":
        raise invalid("form_unknown")
    if form.effective_status(_today(db)) != "active":
        raise invalid("form_not_active")
    _, report = _form_parts(db, form)
    today = _today(db)
    if body.school_id not in assignments.school_ids_for_supervisor(db, supervisor.id, today):
        deny(db, "school", body.school_id)
    if report.subject_type == "teacher":
        teacher = db.get(Teacher, body.teacher_id) if body.teacher_id else None
        if teacher is None or teacher.school_id != body.school_id or teacher.status != "active":
            raise invalid("teacher_not_at_school")
    elif body.teacher_id is not None:
        raise invalid("form_is_for_schools")
    e = Evaluation(
        form_version_id=form.id,
        subject_type=report.subject_type,
        school_id=body.school_id,
        teacher_id=body.teacher_id,
        supervisor_id=supervisor.id,
        client_key=body.client_key,
    )
    _check_visit_date(db, e, body.visit_date)
    e.visit_date = body.visit_date
    db.add(e)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "duplicate_client_key") from exc
    for s in form_schema.parse(form.schema).sections:
        if s.respondent == "supervisor":
            db.add(
                EvaluationSection(
                    evaluation_id=e.id, section_key=s.key, respondent="supervisor", respondent_user_id=principal.user.id
                )
            )
    requests.create_for_evaluation(db, principal, e, form)
    school = db.get(School, e.school_id)
    audit.record(
        db,
        "evaluation.started",
        entity_type="evaluation",
        entity_id=e.id,
        cluster_id=school.cluster_id,
        after={"form_id": form.id, "school_id": e.school_id, "teacher_id": e.teacher_id},
    )
    db.commit()
    return e


def save(db: Session, principal: Principal, evaluation_id: int, body: SaveIn) -> Evaluation:
    e = _locked_own(db, principal, evaluation_id, body.version)
    if e.status not in EDITABLE:
        raise AppError(409, "evaluation_locked")
    if "visit_date" in body.model_fields_set:
        _check_visit_date(db, e, body.visit_date)
        e.visit_date = body.visit_date
    if "visit_notes" in body.model_fields_set:
        e.visit_notes = body.visit_notes
    _apply_answers(db, principal, e, body.sections, complete=False)
    e.updated_at = clock.now()
    db.flush()
    audit.record(
        db, "evaluation.saved", entity_type="evaluation", entity_id=e.id, after={"sections": sorted(body.sections)}
    )
    db.commit()
    return e


def _form_open_for_submission(db: Session, e: Evaluation, *, queued: bool = False) -> None:
    """FR-PB4: drafts started in the window can be submitted until the end date.

    FR-PW13: a submission made offline and sent after the form closed is still accepted
    if its visit date falls inside the form's window. Otherwise the draft stays a draft.
    """
    form = db.get(FormVersion, e.form_version_id)
    closed = form.closed_at is not None or (form.end_date is not None and _today(db) > form.end_date)
    if not closed:
        return
    if queued and e.visit_date is not None and form.start_date and form.end_date:
        last_day = (
            min(form.end_date, clock.local_date(get_district(db).time_zone, form.closed_at))
            if form.closed_at
            else form.end_date
        )
        if form.start_date <= e.visit_date <= last_day:
            return
    raise AppError(409, "form_closed")


def submit(db: Session, principal: Principal, evaluation_id: int, body: SubmitIn) -> Evaluation:
    e = _locked_own(db, principal, evaluation_id, body.version)
    if e.status != "draft":
        raise AppError(409, "evaluation_locked")
    _form_open_for_submission(db, e, queued=body.device_time is not None)
    requests.check_ready(db, e)
    if e.visit_date is None:
        raise invalid("answers_invalid", [{"where": "visit_date", "code": "required"}])
    _check_visit_date(db, e, e.visit_date)
    _apply_answers(db, principal, e, {}, complete=True)
    now = clock.now()
    for row in _sections(db, e):
        if row.respondent == "supervisor":
            row.status, row.submitted_at = "submitted", now
    if body.location is not None:
        # FR-E8: captured only at submission, with the device's permission.
        e.latitude, e.longitude = body.location.latitude, body.location.longitude
        e.location_accuracy_m = body.location.accuracy_m
    e.status, e.submitted_at = "submitted", now
    db.flush()
    school = db.get(School, e.school_id)
    audit.record(
        db,
        "evaluation.submitted",
        entity_type="evaluation",
        entity_id=e.id,
        cluster_id=school.cluster_id,
        after={"visit_date": e.visit_date, "location_captured": body.location is not None},
    )
    if body.device_time and abs(body.device_time - clock.now()) > timedelta(hours=24):
        # FR-PW11: both times are kept; a device clock far off is flagged for review.
        audit.record(
            db,
            "evaluation.clock_skew",
            entity_type="evaluation",
            entity_id=e.id,
            severity="warning",
            after={"device_time": body.device_time, "received": clock.now()},
        )
    _notify_reviewers(db, e, "evaluation_submitted")
    db.commit()
    return e


def amend(db: Session, principal: Principal, evaluation_id: int, body: AmendIn) -> Evaluation:
    """FR-E7: corrections keep the reason and what they replaced."""
    e = _locked_own(db, principal, evaluation_id, body.version)
    if e.status not in ("submitted", "amended"):
        raise AppError(409, "evaluation_not_submitted")
    prior = {
        "visit_date": e.visit_date.isoformat() if e.visit_date else None,
        "visit_notes": e.visit_notes,
        "sections": {s.section_key: s.answers for s in _sections(db, e)},
    }
    if "visit_date" in body.model_fields_set and body.visit_date is not None:
        _check_visit_date(db, e, body.visit_date)
        e.visit_date = body.visit_date
    if "visit_notes" in body.model_fields_set:
        e.visit_notes = body.visit_notes
    _apply_answers(db, principal, e, body.sections, complete=True)
    for row in _sections(db, e):
        if row.respondent == "supervisor":
            row.status = "submitted"
    db.add(EvaluationAmendment(evaluation_id=e.id, reason=body.reason, prior=prior, created_by=principal.user.id))
    e.status, e.amended_at = "amended", clock.now()
    db.flush()
    school = db.get(School, e.school_id)
    audit.record(
        db,
        "evaluation.amended",
        entity_type="evaluation",
        entity_id=e.id,
        cluster_id=school.cluster_id,
        after={"reason": body.reason, "sections": sorted(body.sections)},
    )
    _notify_reviewers(db, e, "evaluation_amended", reason=body.reason)
    db.commit()
    return e


def cancel(db: Session, principal: Principal, evaluation_id: int, body: CancelIn) -> Evaluation:
    """FR-E9: a draft can be cancelled with a reason. Submitted evaluations are records and stay."""
    e = _locked_own(db, principal, evaluation_id, body.version)
    if e.status != "draft":
        raise AppError(409, "evaluation_locked")
    e.status, e.cancelled_at, e.cancel_reason = "cancelled", clock.now(), body.reason
    requests.close_for_evaluation(db, e, body.reason)
    db.flush()
    audit.record(db, "evaluation.cancelled", entity_type="evaluation", entity_id=e.id, after={"reason": body.reason})
    db.commit()
    return e


def amendments(db: Session, principal: Principal, evaluation_id: int) -> list[dict[str, Any]]:
    get_evaluation(db, principal, evaluation_id)
    rows = db.execute(
        select(EvaluationAmendment, User)
        .join(User, User.id == EvaluationAmendment.created_by)
        .where(EvaluationAmendment.evaluation_id == evaluation_id)
        .order_by(EvaluationAmendment.id)
    ).all()
    return [{"reason": a.reason, "prior": a.prior, "by": u.name, "at": a.created_at} for a, u in rows]


def list_evaluations(
    db: Session,
    principal: Principal,
    *,
    status: str | None = None,
    school_id: int | None = None,
    form_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    query = select(Evaluation).order_by(Evaluation.id.desc())
    if principal.role == Role.SUPERVISOR:
        own = _own_supervisor(db, principal)
        query = query.where(Evaluation.supervisor_id == own.id)
    elif principal.role == Role.CLUSTER_HEAD:
        query = query.join(School, School.id == Evaluation.school_id).where(
            School.cluster_id.in_(managed_cluster_ids(db, principal) or [])
        )
    elif principal.role != Role.DISTRICT_ADMIN:
        raise AppError(403, "forbidden")
    if status:
        query = query.where(Evaluation.status == status)
    if school_id:
        query = query.where(Evaluation.school_id == school_id)
    if form_id:
        query = query.where(Evaluation.form_version_id == form_id)
    rows, total = paginate(db, query, page, page_size)
    return {"items": [evaluation_out(db, e, full=False) for (e,) in rows], "total": total, "page": page}


def cluster_of(db: Session, e: Evaluation) -> Cluster:
    return db.get(Cluster, db.get(School, e.school_id).cluster_id)
