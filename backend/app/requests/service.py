"""Teacher requests (section 8.6): routing, answering, returns, waivers, reminders.

A request carries a form's teacher sections to one teacher:

- For a School evaluation, the school's contact teacher (FR-E2). The request follows
  the contact role: when the Cluster Head names a new contact, an unstarted request
  moves at once, and a started one moves only when the requester confirms (FR-S6,
  section 6.1). Until the school has a contact, the request waits unaddressed.
- For a Teacher evaluation, the teacher being evaluated (FR-E3). It stays with them if
  they transfer (section 6.1).
- For a standalone request, the teachers chosen, or a school's contact teacher, on a
  published form a District Admin approved for standalone use (FR-R1).

The teacher saves drafts and submits; the requester may return it with a comment and the
teacher resubmits; every step is audited (FR-R4, FR-R5). An evaluation cannot be submitted
until its request is submitted or waived by the Cluster Head (FR-E6). Reminders go out
three days before the due date, on it, and once overdue, through the daily digest (FR-R6).
"""

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
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
    AuditLog,
    Evaluation,
    FormVersion,
    MinistryReport,
    MinistryReportVersion,
    Role,
    School,
    StoredFile,
    Supervisor,
    Teacher,
    TeacherRequest,
    User,
)
from app.notifications import service as notify
from app.structure.common import deny, managed_cluster_ids
from app.structure.service import current_contact, paginate

from . import access

OPEN = ("not_started", "in_progress", "returned")
ANSWERABLE = OPEN
DEFAULT_DUE_DAYS = 7
REMINDER_DAYS_BEFORE = 3


class SaveIn(BaseModel):
    version: int
    sections: dict[str, dict[str, Any]] = Field(default_factory=dict)


class VersionIn(BaseModel):
    version: int


class ReturnIn(VersionIn):
    comment: str = Field(min_length=1, max_length=5000)


class ReasonIn(VersionIn):
    reason: str = Field(min_length=1, max_length=1000)


class SettingsIn(VersionIn):
    due_date: date | None = None
    instructions: str | None = Field(default=None, max_length=5000)


class ConfirmIn(VersionIn):
    accept: bool


class CreateIn(BaseModel):
    form_id: int
    due_date: date
    instructions: str | None = Field(default=None, max_length=5000)
    # Either schools, whose contact teachers answer, or named teachers.
    school_ids: list[int] = Field(default_factory=list, max_length=200)
    teacher_ids: list[int] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _some_recipient(self) -> "CreateIn":
        if not self.school_ids and not self.teacher_ids:
            raise ValueError("choose schools or teachers")
        return self


def _today(db: Session) -> date:
    return clock.local_date(get_district(db).time_zone)


def teacher_sections(form: FormVersion) -> list[form_schema.Section]:
    return [s for s in form_schema.parse(form.schema).sections if s.respondent == "teacher"]


def is_overdue(db: Session, r: TeacherRequest) -> bool:
    # A due date ends at 23:59 district time (FR-R2).
    return r.status in OPEN and _today(db) > r.due_date


def _parts(db: Session, r: TeacherRequest) -> tuple[FormVersion, MinistryReportVersion, MinistryReport]:
    form = db.get(FormVersion, r.form_version_id)
    mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
    return form, mrv, db.get(MinistryReport, mrv.ministry_report_id)


def _teacher_name(db: Session, teacher_id: int | None) -> str | None:
    if teacher_id is None:
        return None
    return db.get(User, db.get(Teacher, teacher_id).user_id).name


def _params(db: Session, r: TeacherRequest, **extra: Any) -> dict[str, Any]:
    _, mrv, report = _parts(db, r)
    return {
        "report_code": report.report_code,
        "version_code": mrv.version_code,
        "school": db.get(School, r.school_id).name,
        "teacher": _teacher_name(db, r.teacher_id) or "",
        "due": r.due_date,
        "request_id": r.id,
        **extra,
    }


def _requester_user_id(db: Session, r: TeacherRequest) -> int:
    if r.evaluation_id is not None:
        e = db.get(Evaluation, r.evaluation_id)
        return db.get(Supervisor, e.supervisor_id).user_id
    return r.requested_by


def _notify_teacher(db: Session, teacher_id: int | None, type_: str, params: dict[str, Any]) -> None:
    if teacher_id is not None:
        notify.notify(db, db.get(Teacher, teacher_id).user_id, type_, params)


def _audit(db: Session, action: str, r: TeacherRequest, **after: Any) -> None:
    audit.record(
        db,
        action,
        entity_type="request",
        entity_id=r.id,
        cluster_id=db.get(School, r.school_id).cluster_id,
        after=after or None,
    )


def request_out(db: Session, principal: Principal, r: TeacherRequest, *, full: bool = False) -> dict[str, Any]:
    form, mrv, report = _parts(db, r)
    school = db.get(School, r.school_id)
    requester = db.get(User, _requester_user_id(db, r))
    evaluation = db.get(Evaluation, r.evaluation_id) if r.evaluation_id else None
    out: dict[str, Any] = {
        "id": r.id,
        "kind": r.kind,
        "report": {
            "code": report.report_code,
            "version_code": mrv.version_code,
            "title_en": mrv.title_en,
            "title_ar": mrv.title_ar,
        },
        "school": {"id": school.id, "code": school.code, "name": school.name},
        "teacher": {"id": r.teacher_id, "name": _teacher_name(db, r.teacher_id)} if r.teacher_id else None,
        "pending_teacher": (
            {"id": r.pending_teacher_id, "name": _teacher_name(db, r.pending_teacher_id)}
            if r.pending_teacher_id
            else None
        ),
        "via_contact": r.via_contact,
        "requester": requester.name,
        "evaluation": (
            {
                "id": evaluation.id,
                "subject_type": evaluation.subject_type,
                "status": evaluation.status,
                "about": _teacher_name(db, evaluation.teacher_id),
            }
            if evaluation
            else None
        ),
        "status": r.status,
        "overdue": is_overdue(db, r),
        "due_date": r.due_date,
        "submitted_at": r.submitted_at,
        "returned_at": r.returned_at,
        "return_comment": r.return_comment,
        "return_count": r.return_count,
        "closed_at": r.closed_at,
        "close_reason": r.close_reason,
        "version": r.version,
        "can": {
            "answer": access.is_respondent(db, principal, r) and r.status in ANSWERABLE and _still_open(db, r),
            "manage": access.is_requester(db, principal, r),
            "waive": access.can_waive(db, principal, r) and r.status in OPEN,
        },
    }
    if full:
        out["instructions"] = r.instructions
        # Only the teacher sections: a teacher never sees the supervisor's (FR-E10).
        out["sections"] = [s.model_dump(mode="json") for s in teacher_sections(form)]
        # Others see the teacher's answers once submitted, not their drafts.
        shown = access.is_respondent(db, principal, r) or r.status in ("submitted", "returned")
        out["answers"] = r.answers if shown else {}
    return out


def _still_open(db: Session, r: TeacherRequest) -> bool:
    if r.evaluation_id is None:
        return True
    return db.get(Evaluation, r.evaluation_id).status == "draft"


def _locked(db: Session, principal: Principal, request_id: int, version: int) -> TeacherRequest:
    access.get_visible(db, principal, request_id)
    r = db.execute(
        select(TeacherRequest)
        .where(TeacherRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if r.version != version:
        raise AppError(409, "version_conflict", {"current": request_out(db, principal, r)})
    return r


# Routing -------------------------------------------------------------------------------------


def _default_due(db: Session, form: FormVersion) -> date:
    today = _today(db)
    due = today + timedelta(days=DEFAULT_DUE_DAYS)
    return max(today, min(due, form.end_date)) if form.end_date else due


def create_for_evaluation(db: Session, principal: Principal, e: Evaluation, form: FormVersion) -> None:
    """FR-E2, FR-E3: a form with teacher sections sends them to the right teacher."""
    if not teacher_sections(form):
        return
    if e.subject_type == "teacher":
        teacher_id, via_contact = e.teacher_id, False
    else:
        contact = current_contact(db, e.school_id)
        teacher_id, via_contact = (contact.teacher_id if contact else None), True
    r = TeacherRequest(
        kind="evaluation",
        form_version_id=form.id,
        evaluation_id=e.id,
        school_id=e.school_id,
        via_contact=via_contact,
        teacher_id=teacher_id,
        requested_by=principal.user.id,
        due_date=_default_due(db, form),
    )
    db.add(r)
    db.flush()
    _audit(db, "request.created", r, teacher_id=teacher_id, evaluation_id=e.id)
    _notify_teacher(db, teacher_id, "request_assigned", _params(db, r))


def summary(db: Session, r: TeacherRequest) -> dict[str, Any]:
    """The request as shown on its evaluation."""
    return {
        "id": r.id,
        "status": r.status,
        "overdue": is_overdue(db, r),
        "due_date": r.due_date,
        "teacher": {"id": r.teacher_id, "name": _teacher_name(db, r.teacher_id)} if r.teacher_id else None,
        "pending_teacher": _teacher_name(db, r.pending_teacher_id),
        "return_count": r.return_count,
        "close_reason": r.close_reason,
    }


def evaluation_request(db: Session, e: Evaluation) -> TeacherRequest | None:
    return db.execute(select(TeacherRequest).where(TeacherRequest.evaluation_id == e.id)).scalar_one_or_none()


def check_ready(db: Session, e: Evaluation) -> None:
    """FR-E6: teacher sections are submitted, or the Cluster Head waived them."""
    r = evaluation_request(db, e)
    if r is not None and r.status not in ("submitted", "waived"):
        raise AppError(409, "teacher_section_pending", {"request_id": r.id, "status": r.status})


def evaluation_sections(db: Session, e: Evaluation) -> list[dict[str, Any]]:
    """Teacher sections as they appear on the evaluation and its PDF."""
    r = evaluation_request(db, e)
    if r is None:
        return []
    status = {"not_started": "not_started", "in_progress": "in_progress", "returned": "returned"}.get(
        r.status, r.status
    )
    return [
        {
            "key": s.key,
            "respondent": "teacher",
            "status": status,
            "answers": r.answers.get(s.key, {}) if r.status == "submitted" else {},
            "submitted_at": r.submitted_at,
        }
        for s in teacher_sections(db.get(FormVersion, r.form_version_id))
    ]


def close_for_evaluation(db: Session, e: Evaluation, reason: str) -> None:
    """A cancelled evaluation cancels its open request."""
    r = evaluation_request(db, e)
    if r is None or r.status not in OPEN:
        return
    r.status, r.closed_at, r.close_reason = "cancelled", clock.now(), reason
    db.flush()
    _audit(db, "request.cancelled", r, reason=reason)
    _notify_teacher(db, r.teacher_id, "request_cancelled", _params(db, r))


def on_contact_changed(db: Session, school_id: int, new_teacher_id: int) -> None:
    """FR-S6, section 6.1: requests addressed to the school's contact follow the role."""
    rows = db.execute(
        select(TeacherRequest)
        .where(
            TeacherRequest.school_id == school_id,
            TeacherRequest.via_contact.is_(True),
            TeacherRequest.status.in_(OPEN),
        )
        .with_for_update()
    ).scalars()
    for r in rows:
        if r.teacher_id == new_teacher_id:
            r.pending_teacher_id = None
            continue
        if r.teacher_id is None or r.status == "not_started":
            previous = r.teacher_id
            r.teacher_id, r.pending_teacher_id = new_teacher_id, None
            db.flush()
            _audit(db, "request.moved", r, from_teacher_id=previous, to_teacher_id=new_teacher_id)
            _notify_teacher(db, new_teacher_id, "request_assigned", _params(db, r))
            notify.notify(db, _requester_user_id(db, r), "request_moved", _params(db, r))
        else:
            # Someone has started answering: the requester decides who finishes it.
            r.pending_teacher_id = new_teacher_id
            db.flush()
            _audit(db, "request.move_pending", r, to_teacher_id=new_teacher_id)
            notify.notify(
                db,
                _requester_user_id(db, r),
                "request_move_confirm",
                _params(db, r, new_teacher=_teacher_name(db, new_teacher_id)),
            )


def on_supervisor_changed(db: Session, e: Evaluation, user_id: int) -> None:
    """Drafts transferred to another supervisor take their request along (FR-AS9)."""
    r = evaluation_request(db, e)
    if r is not None:
        r.requested_by = user_id


# Teacher ---------------------------------------------------------------------------------------


def _file_checker(db: Session, principal: Principal, r: TeacherRequest):
    def ok(ids: list[int]) -> bool:
        for file_id in ids:
            file = db.get(StoredFile, file_id)
            if file is None or file.uploaded_by != principal.user.id or file.scan_status == "quarantined":
                return False
            if file.owner_type not in ("upload", "request") or (file.owner_type == "request" and file.owner_id != r.id):
                return False
        return True

    return ok


def _request_files_rule(db: Session, principal: Principal, file: StoredFile) -> bool:
    r = db.get(TeacherRequest, file.owner_id)
    return (
        r is not None
        and db.execute(access.visible_query(db, principal).where(TeacherRequest.id == r.id)).first() is not None
    )


files.register_owner("request", _request_files_rule)


def _apply(
    db: Session, principal: Principal, r: TeacherRequest, sections: dict[str, dict[str, Any]], *, complete: bool
) -> None:
    form = db.get(FormVersion, r.form_version_id)
    parsed = form_schema.parse(form.schema)
    keys = {s.key for s in teacher_sections(form)}
    checker = _file_checker(db, principal, r)
    problems: list[dict[str, str]] = []
    answers = dict(r.answers)
    for key, given in sections.items():
        if key not in keys:
            problems.append({"where": key, "code": "section_not_yours"})
            continue
        cleaned, found = form_schema.validate_answers(parsed, key, given, complete=False, file_ok=checker)
        problems += [{**p, "where": f"{key}.{p['where']}"} for p in found]
        if not found:
            answers[key] = cleaned
            for q in next(s for s in parsed.sections if s.key == key).questions:
                if q.type == "file":
                    for file_id in cleaned.get(q.key) or []:
                        stored = db.get(StoredFile, file_id)
                        stored.owner_type, stored.owner_id = "request", r.id
    if complete:
        for key in keys:
            _, found = form_schema.validate_answers(parsed, key, answers.get(key, {}), complete=True, file_ok=checker)
            problems += [{**p, "where": f"{key}.{p['where']}"} for p in found]
    if problems:
        raise invalid("answers_invalid", problems)
    r.answers = answers


def _own_open(db: Session, principal: Principal, request_id: int, version: int) -> TeacherRequest:
    r = _locked(db, principal, request_id, version)
    if not access.is_respondent(db, principal, r):
        raise AppError(403, "forbidden")
    if r.status not in ANSWERABLE or not _still_open(db, r):
        raise AppError(409, "request_locked")
    return r


def save(db: Session, principal: Principal, request_id: int, body: SaveIn) -> TeacherRequest:
    """FR-R4: drafts may be partial but must be well typed."""
    r = _own_open(db, principal, request_id, body.version)
    _apply(db, principal, r, body.sections, complete=False)
    if r.status == "not_started":
        r.status = "in_progress"
    db.flush()
    _audit(db, "request.saved", r, sections=sorted(body.sections))
    db.commit()
    return r


def submit(db: Session, principal: Principal, request_id: int, body: SaveIn) -> TeacherRequest:
    r = _own_open(db, principal, request_id, body.version)
    _apply(db, principal, r, body.sections, complete=True)
    resubmitted = r.status == "returned"
    r.status, r.submitted_at = "submitted", clock.now()
    db.flush()
    _audit(db, "request.resubmitted" if resubmitted else "request.submitted", r)
    notify.notify(db, _requester_user_id(db, r), "request_submitted", _params(db, r))
    db.commit()
    return r


# Requester and Cluster Head ----------------------------------------------------------------------


def _as_requester(db: Session, principal: Principal, request_id: int, version: int) -> TeacherRequest:
    r = _locked(db, principal, request_id, version)
    if not access.is_requester(db, principal, r):
        raise AppError(403, "forbidden")
    return r


def return_(db: Session, principal: Principal, request_id: int, body: ReturnIn) -> TeacherRequest:
    """FR-R5: back to the teacher with a comment, while the evaluation is still open."""
    r = _as_requester(db, principal, request_id, body.version)
    if r.status != "submitted" or not _still_open(db, r):
        raise AppError(409, "request_not_returnable")
    r.status, r.returned_at, r.return_comment = "returned", clock.now(), body.comment
    r.return_count += 1
    db.flush()
    _audit(db, "request.returned", r, comment=body.comment, count=r.return_count)
    _notify_teacher(db, r.teacher_id, "request_returned", _params(db, r, comment=body.comment))
    db.commit()
    return r


def update_settings(db: Session, principal: Principal, request_id: int, body: SettingsIn) -> TeacherRequest:
    r = _as_requester(db, principal, request_id, body.version)
    if r.status not in OPEN:
        raise AppError(409, "request_locked")
    changed: dict[str, Any] = {}
    if body.due_date is not None and body.due_date != r.due_date:
        if body.due_date < _today(db):
            raise invalid("due_date_in_past")
        changed["due_date"] = body.due_date
        r.due_date = body.due_date
        # A new due date earns its reminders again.
        r.reminders = []
    if "instructions" in body.model_fields_set:
        r.instructions = body.instructions
        changed["instructions"] = True
    db.flush()
    _audit(db, "request.settings_changed", r, **changed)
    if "due_date" in changed:
        _notify_teacher(db, r.teacher_id, "request_due_changed", _params(db, r))
    db.commit()
    return r


def waive(db: Session, principal: Principal, request_id: int, body: ReasonIn) -> TeacherRequest:
    """FR-E6: the Cluster Head lets the evaluation go ahead without the teacher's answers."""
    r = _locked(db, principal, request_id, body.version)
    if not access.can_waive(db, principal, r):
        raise AppError(403, "forbidden")
    if r.status not in OPEN:
        raise AppError(409, "request_locked")
    r.status, r.closed_by, r.closed_at, r.close_reason = "waived", principal.user.id, clock.now(), body.reason
    r.pending_teacher_id = None
    db.flush()
    _audit(db, "request.waived", r, reason=body.reason)
    params = _params(db, r, reason=body.reason)
    _notify_teacher(db, r.teacher_id, "request_waived", params)
    notify.notify(db, _requester_user_id(db, r), "request_waived", params)
    db.commit()
    return r


def cancel(db: Session, principal: Principal, request_id: int, body: ReasonIn) -> TeacherRequest:
    """Standalone requests only: an evaluation's request ends with the evaluation."""
    r = _as_requester(db, principal, request_id, body.version)
    if r.kind != "standalone":
        raise AppError(409, "cancel_the_evaluation")
    if r.status not in OPEN:
        raise AppError(409, "request_locked")
    r.status, r.closed_by, r.closed_at, r.close_reason = "cancelled", principal.user.id, clock.now(), body.reason
    db.flush()
    _audit(db, "request.cancelled", r, reason=body.reason)
    _notify_teacher(db, r.teacher_id, "request_cancelled", _params(db, r))
    db.commit()
    return r


def confirm_move(db: Session, principal: Principal, request_id: int, body: ConfirmIn) -> TeacherRequest:
    """Section 6.1: the requester confirms that the new contact teacher takes over."""
    r = _as_requester(db, principal, request_id, body.version)
    if r.pending_teacher_id is None:
        raise AppError(409, "no_move_pending")
    new_teacher = r.pending_teacher_id
    r.pending_teacher_id = None
    if body.accept:
        previous = r.teacher_id
        r.teacher_id = new_teacher
        db.flush()
        _audit(db, "request.moved", r, from_teacher_id=previous, to_teacher_id=new_teacher, confirmed=True)
        _notify_teacher(db, new_teacher, "request_assigned", _params(db, r))
        _notify_teacher(db, previous, "request_moved_away", _params(db, r))
    else:
        db.flush()
        _audit(db, "request.move_declined", r, to_teacher_id=new_teacher)
    db.commit()
    return r


# Standalone requests (FR-R1) ---------------------------------------------------------------------


def _may_request_school(db: Session, principal: Principal, school: School) -> bool:
    if principal.role == Role.DISTRICT_ADMIN:
        return True
    if principal.role == Role.CLUSTER_HEAD:
        return school.cluster_id in (managed_cluster_ids(db, principal) or [])
    if principal.role == Role.SUPERVISOR:
        own = assignments.supervisor_for_user(db, principal.user.id)
        return own is not None and school.id in assignments.school_ids_for_supervisor(db, own.id, _today(db))
    return False


def create_standalone(db: Session, principal: Principal, body: CreateIn) -> list[TeacherRequest]:
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR):
        raise AppError(403, "forbidden")
    form = db.get(FormVersion, body.form_id)
    if form is None or form.status != "published":
        raise invalid("form_unknown")
    if form.effective_status(_today(db)) != "active":
        raise invalid("form_not_active")
    mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
    if not db.get(MinistryReport, mrv.ministry_report_id).standalone_allowed:
        raise invalid("form_not_for_requests")
    if not teacher_sections(form):
        raise invalid("form_has_no_teacher_sections")
    if body.due_date < _today(db):
        raise invalid("due_date_in_past")
    targets: list[tuple[int, int | None, bool]] = []
    for school_id in dict.fromkeys(body.school_ids):
        school = db.get(School, school_id)
        if school is None or school.status != "active" or not _may_request_school(db, principal, school):
            deny(db, "school", school_id)
        contact = current_contact(db, school.id)
        targets.append((school.id, contact.teacher_id if contact else None, True))
    for teacher_id in dict.fromkeys(body.teacher_ids):
        teacher = db.get(Teacher, teacher_id)
        if teacher is None or teacher.status != "active":
            raise invalid("teacher_unknown")
        if not _may_request_school(db, principal, db.get(School, teacher.school_id)):
            deny(db, "teacher", teacher_id)
        targets.append((teacher.school_id, teacher.id, False))
    created = []
    for school_id, teacher_id, via_contact in targets:
        r = TeacherRequest(
            kind="standalone",
            form_version_id=form.id,
            school_id=school_id,
            via_contact=via_contact,
            teacher_id=teacher_id,
            requested_by=principal.user.id,
            due_date=body.due_date,
            instructions=body.instructions,
        )
        db.add(r)
        db.flush()
        _audit(db, "request.created", r, teacher_id=teacher_id, form_id=form.id)
        _notify_teacher(db, teacher_id, "request_assigned", _params(db, r))
        created.append(r)
    db.commit()
    return created


def set_standalone_allowed(db: Session, principal: Principal, report_id: int, allowed: bool) -> MinistryReport:
    if principal.role != Role.DISTRICT_ADMIN:
        raise AppError(403, "forbidden")
    report = db.get(MinistryReport, report_id)
    if report is None:
        raise not_found()
    report.standalone_allowed = allowed
    audit.record(
        db, "catalog.standalone_changed", entity_type="ministry_report", entity_id=report.id, after={"allowed": allowed}
    )
    db.commit()
    return report


# Lists and history ------------------------------------------------------------------------------------


Filter = Literal["open", "overdue", "submitted", "closed", "awaiting_confirmation", "unaddressed"]


def list_requests(
    db: Session,
    principal: Principal,
    *,
    show: Filter | None = None,
    school_id: int | None = None,
    kind: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    query = access.visible_query(db, principal)
    today = _today(db)
    if show == "open":
        query = query.where(TeacherRequest.status.in_(OPEN))
    elif show == "overdue":
        query = query.where(TeacherRequest.status.in_(OPEN), TeacherRequest.due_date < today)
    elif show == "submitted":
        query = query.where(TeacherRequest.status == "submitted")
    elif show == "closed":
        query = query.where(TeacherRequest.status.in_(("waived", "cancelled")))
    elif show == "awaiting_confirmation":
        query = query.where(TeacherRequest.pending_teacher_id.is_not(None))
    elif show == "unaddressed":
        query = query.where(TeacherRequest.teacher_id.is_(None), TeacherRequest.status.in_(OPEN))
    if school_id is not None:
        query = query.where(TeacherRequest.school_id == school_id)
    if kind is not None:
        query = query.where(TeacherRequest.kind == kind)
    query = query.order_by(TeacherRequest.due_date, TeacherRequest.id)
    rows, total = paginate(db, query, page, page_size)
    return {"items": [request_out(db, principal, r) for (r,) in rows], "total": total, "page": page}


def history(db: Session, principal: Principal, request_id: int) -> list[dict[str, Any]]:
    """FR-R5: every step, from the audit log. Not for the teacher, who sees the status."""
    r = access.get_visible(db, principal, request_id)
    if principal.role == Role.TEACHER:
        raise AppError(403, "forbidden")
    rows = db.execute(
        select(AuditLog, User)
        .join(User, User.id == AuditLog.actor_id, isouter=True)
        .where(AuditLog.entity_type == "request", AuditLog.entity_id == str(r.id), AuditLog.action != "request.saved")
        .order_by(AuditLog.seq)
    ).all()
    return [
        {
            "action": a.action.removeprefix("request."),
            "by": u.name if u else None,
            "at": a.created_at,
            "detail": a.after,
        }
        for a, u in rows
    ]


# Reminders (FR-R6) -------------------------------------------------------------------------------------


def remind(db: Session) -> int:
    """Daily, before the digest: 3 days before, on the due date, and once overdue."""
    today = _today(db)
    sent = 0
    rows = db.execute(
        select(TeacherRequest)
        .where(TeacherRequest.status.in_(OPEN), TeacherRequest.teacher_id.is_not(None))
        .with_for_update()
    ).scalars()
    for r in rows:
        if not _still_open(db, r):
            continue
        marks = list(r.reminders or [])
        if today > r.due_date:
            step = "overdue"
        elif today == r.due_date:
            step = "due"
        elif today >= r.due_date - timedelta(days=REMINDER_DAYS_BEFORE):
            step = "soon"
        else:
            continue
        if step in marks:
            continue
        params = _params(db, r)
        _notify_teacher(
            db,
            r.teacher_id,
            {"soon": "request_due_soon", "due": "request_due_today", "overdue": "request_overdue"}[step],
            params,
        )
        if step == "overdue":
            notify.notify(db, _requester_user_id(db, r), "request_overdue_requester", params)
        r.reminders = [*marks, step]
        sent += 1
    db.commit()
    return sent
