"""Ministry report catalog, form drafting, review and publishing (sections 8.1 to 8.3).

Form Authors build forms as drafts and send them for review. District Admins
return them with comments or publish them with a start and end date. A
published form's content never changes; only its window can move (FR-PB5).
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.auth.deps import Principal
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.files import service as files
from app.models import FormReviewComment, FormVersion, MinistryReport, MinistryReportVersion, Role, StoredFile, User
from app.notifications import service as notify

from . import schema as form_schema

CODE = r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,63}$"
AUTHORS = (Role.FORM_AUTHOR,)
REVIEWERS = (Role.DISTRICT_ADMIN,)
CATALOG_READERS = (Role.DISTRICT_ADMIN, Role.FORM_AUTHOR, Role.CLUSTER_HEAD, Role.SUPERVISOR)


class ReportIn(BaseModel):
    report_code: str = Field(pattern=CODE)
    subject_type: str = Field(pattern="^(school|teacher)$")


class VersionIn(BaseModel):
    version_code: str = Field(pattern=CODE)
    title_en: str = Field(default="", max_length=300)
    title_ar: str = Field(default="", max_length=300)
    ministry_published_on: date | None = None
    source_file_id: int | None = None
    copy_from_form_id: int | None = None


class FormUpdate(BaseModel):
    version: int
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    title_en: str | None = Field(default=None, max_length=300)
    title_ar: str | None = Field(default=None, max_length=300)
    ministry_published_on: date | None = None
    source_file_id: int | None = None


class PublishIn(BaseModel):
    version: int
    start_date: date
    end_date: date
    confirm_overlap: bool = False


class WindowIn(BaseModel):
    version: int
    end_date: date
    reason: str = Field(min_length=1, max_length=500)


class CloseIn(BaseModel):
    version: int
    reason: str = Field(min_length=1, max_length=500)


class CommentIn(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)


def _today(db: Session) -> date:
    return clock.local_date(get_district(db).time_zone)


def _require(principal: Principal, roles: tuple[Role, ...]) -> None:
    if principal.role not in roles:
        raise AppError(403, "forbidden")


def _source_rule(_db: Session, principal: Principal, _file: StoredFile) -> bool:
    # The ministry's own document is reference material for all staff.
    return principal.role in CATALOG_READERS


files.register_owner("ministry_source", _source_rule)


def _attach_source(db: Session, principal: Principal, mrv: MinistryReportVersion, file_id: int | None) -> None:
    if file_id is None or file_id == mrv.source_file_id:
        return
    file = files.get_file(db, principal, file_id)
    if file.owner_type != "upload":
        raise invalid("file_in_use")
    file.owner_type, file.owner_id = "ministry_source", mrv.id
    mrv.source_file_id = file.id


def _parts(db: Session, form: FormVersion) -> tuple[MinistryReportVersion, MinistryReport]:
    mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
    return mrv, db.get(MinistryReport, mrv.ministry_report_id)


def form_out(
    db: Session, form: FormVersion, *, with_schema: bool = True, with_problems: bool = False
) -> dict[str, Any]:
    mrv, report = _parts(db, form)
    out: dict[str, Any] = {
        "id": form.id,
        "report": {"id": report.id, "code": report.report_code, "subject_type": report.subject_type},
        "catalog": {
            "id": mrv.id,
            "version_code": mrv.version_code,
            "title_en": mrv.title_en,
            "title_ar": mrv.title_ar,
            "ministry_published_on": mrv.ministry_published_on,
            "source_file_id": mrv.source_file_id,
        },
        "status": form.effective_status(_today(db)),
        "start_date": form.start_date,
        "end_date": form.end_date,
        "closed_at": form.closed_at,
        "version": form.version,
    }
    if with_schema:
        out["schema"] = form.schema
    if with_problems:
        out["problems"] = _all_problems(form, mrv)
    return out


def _all_problems(form: FormVersion, mrv: MinistryReportVersion) -> list[dict[str, str]]:
    problems = form_schema.completeness_problems(form_schema.parse(form.schema))
    if not mrv.title_en.strip():
        problems.insert(0, {"where": "title", "code": "english_missing"})
    if not mrv.title_ar.strip():
        problems.insert(0, {"where": "title", "code": "arabic_missing"})
    return problems


def _audit(db: Session, action: str, form: FormVersion, **after: Any) -> None:
    audit.record(db, action, entity_type="form", entity_id=form.id, after=after or None)


def _notice_params(db: Session, form: FormVersion) -> dict[str, Any]:
    mrv, report = _parts(db, form)
    return {
        "report_code": report.report_code,
        "version_code": mrv.version_code,
        "start": form.start_date,
        "end": form.end_date,
        "form_id": form.id,
    }


# Catalog -----------------------------------------------------------------------------


def create_report(db: Session, principal: Principal, body: ReportIn) -> MinistryReport:
    _require(principal, AUTHORS)
    if db.execute(select(MinistryReport.id).where(MinistryReport.report_code == body.report_code)).first():
        raise AppError(409, "code_taken")
    report = MinistryReport(report_code=body.report_code, subject_type=body.subject_type, created_by=principal.user.id)
    db.add(report)
    db.flush()
    audit.record(
        db,
        "catalog.report_created",
        entity_type="ministry_report",
        entity_id=report.id,
        after={"report_code": report.report_code, "subject_type": report.subject_type},
    )
    db.commit()
    return report


def create_version(db: Session, principal: Principal, report_id: int, body: VersionIn) -> FormVersion:
    """A new ministry version and its draft form, optionally copied from an earlier form (FR-MR4)."""
    _require(principal, AUTHORS)
    report = db.get(MinistryReport, report_id)
    if report is None:
        raise not_found()
    exists = db.execute(
        select(MinistryReportVersion.id).where(
            MinistryReportVersion.ministry_report_id == report.id,
            MinistryReportVersion.version_code == body.version_code,
        )
    ).first()
    if exists:
        raise AppError(409, "code_taken")
    initial: dict[str, Any] = {"sections": []}
    if body.copy_from_form_id is not None:
        source = db.get(FormVersion, body.copy_from_form_id)
        if source is None:
            raise invalid("copy_source_unknown")
        initial = form_schema.copy_schema(source.schema)
    mrv = MinistryReportVersion(
        ministry_report_id=report.id,
        version_code=body.version_code,
        title_en=body.title_en.strip(),
        title_ar=body.title_ar.strip(),
        ministry_published_on=body.ministry_published_on,
        created_by=principal.user.id,
    )
    db.add(mrv)
    db.flush()
    _attach_source(db, principal, mrv, body.source_file_id)
    form = FormVersion(ministry_report_version_id=mrv.id, schema=initial, built_by=principal.user.id)
    db.add(form)
    db.flush()
    _audit(
        db,
        "form.created",
        form,
        report_code=report.report_code,
        version_code=mrv.version_code,
        copied_from=body.copy_from_form_id,
    )
    db.commit()
    return form


def catalog(db: Session, principal: Principal) -> list[dict[str, Any]]:
    """Ministry reports and their versions. Others than authors and admins see published versions only."""
    _require(principal, CATALOG_READERS)
    builders = principal.role in (Role.FORM_AUTHOR, Role.DISTRICT_ADMIN)
    today = _today(db)
    reports = db.execute(select(MinistryReport).order_by(MinistryReport.report_code)).scalars().all()
    out = []
    for report in reports:
        versions = db.execute(
            select(MinistryReportVersion, FormVersion)
            .join(FormVersion, FormVersion.ministry_report_version_id == MinistryReportVersion.id)
            .where(MinistryReportVersion.ministry_report_id == report.id)
            .order_by(MinistryReportVersion.created_at)
        ).all()
        shown = [
            {
                "id": mrv.id,
                "version_code": mrv.version_code,
                "title_en": mrv.title_en,
                "title_ar": mrv.title_ar,
                "ministry_published_on": mrv.ministry_published_on,
                "source_file_id": mrv.source_file_id,
                "form_id": form.id,
                "status": form.effective_status(today),
                "start_date": form.start_date,
                "end_date": form.end_date,
            }
            for mrv, form in versions
            if builders or form.status == "published"
        ]
        # Builders see a new report before its first version, so they can add one.
        if shown or builders:
            out.append(
                {
                    "id": report.id,
                    "report_code": report.report_code,
                    "subject_type": report.subject_type,
                    "versions": shown,
                }
            )
    return out


def published_version(db: Session, mrv_id: int) -> tuple[MinistryReportVersion, MinistryReport, FormVersion]:
    """A catalog version usable by supervisors (FR-PB7). Used for scanned reports."""
    mrv = db.get(MinistryReportVersion, mrv_id)
    if mrv is None:
        raise invalid("report_version_unknown")
    form = db.execute(select(FormVersion).where(FormVersion.ministry_report_version_id == mrv.id)).scalar_one()
    if form.status != "published":
        raise invalid("report_version_unpublished")
    return mrv, db.get(MinistryReport, mrv.ministry_report_id), form


# Forms ---------------------------------------------------------------------------------


def get_form(db: Session, principal: Principal, form_id: int) -> FormVersion:
    _require(principal, CATALOG_READERS)
    form = db.get(FormVersion, form_id)
    if form is None:
        raise not_found()
    if principal.role not in (Role.FORM_AUTHOR, Role.DISTRICT_ADMIN) and form.status != "published":
        raise not_found()
    return form


def list_forms(db: Session, principal: Principal, status: str | None = None) -> list[dict[str, Any]]:
    _require(principal, CATALOG_READERS)
    builders = principal.role in (Role.FORM_AUTHOR, Role.DISTRICT_ADMIN)
    query = select(FormVersion).order_by(FormVersion.id.desc())
    if not builders:
        query = query.where(FormVersion.status == "published")
    today = _today(db)
    forms = [f for f in db.execute(query).scalars() if status is None or f.effective_status(today) == status]
    return [form_out(db, f, with_schema=False) for f in forms]


def _locked(db: Session, form_id: int, version: int) -> FormVersion:
    form = db.execute(
        select(FormVersion).where(FormVersion.id == form_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if form is None:
        raise not_found()
    if form.version != version:
        raise AppError(409, "version_conflict", {"current": form_out(db, form)})
    return form


def update_form(db: Session, principal: Principal, form_id: int, body: FormUpdate) -> FormVersion:
    """FR-F9: drafts change freely; the structure is checked on every save."""
    _require(principal, AUTHORS)
    form = _locked(db, form_id, body.version)
    if form.status != "draft":
        raise AppError(409, "form_not_draft")
    mrv, _ = _parts(db, form)
    if body.schema_ is not None:
        parsed = form_schema.parse(body.schema_)
        problems = form_schema.structure_problems(parsed)
        if problems:
            raise invalid("form_schema_invalid", problems)
        form.schema = parsed.model_dump(mode="json")
    for field in ("title_en", "title_ar"):
        value = getattr(body, field)
        if value is not None:
            setattr(mrv, field, value.strip())
    if "ministry_published_on" in body.model_fields_set:
        mrv.ministry_published_on = body.ministry_published_on
    _attach_source(db, principal, mrv, body.source_file_id)
    form.updated_at = clock.now()
    db.flush()
    _audit(db, "form.saved", form)
    db.commit()
    return form


def submit_for_review(db: Session, principal: Principal, form_id: int, version: int) -> FormVersion:
    _require(principal, AUTHORS)
    form = _locked(db, form_id, version)
    if form.status != "draft":
        raise AppError(409, "form_not_draft")
    mrv, _ = _parts(db, form)
    problems = _all_problems(form, mrv)
    if problems:
        # FR-F7: a form missing Arabic or English text cannot be sent for review.
        raise invalid("form_incomplete", problems)
    form.status = "in_review"
    form.submitted_at = clock.now()
    db.add(FormReviewComment(form_version_id=form.id, author_id=principal.user.id, action="submitted"))
    db.flush()
    _audit(db, "form.submitted", form)
    notify.notify_role(db, Role.DISTRICT_ADMIN, "form_submitted_for_review", _notice_params(db, form))
    db.commit()
    return form


def return_to_author(db: Session, principal: Principal, form_id: int, version: int, comment: str) -> FormVersion:
    _require(principal, REVIEWERS)
    form = _locked(db, form_id, version)
    if form.status != "in_review":
        raise AppError(409, "form_not_in_review")
    form.status = "draft"
    db.add(FormReviewComment(form_version_id=form.id, author_id=principal.user.id, action="returned", comment=comment))
    db.flush()
    _audit(db, "form.returned", form, comment_length=len(comment))
    notify.notify(db, form.built_by, "form_returned", _notice_params(db, form))
    db.commit()
    return form


def _overlapping(db: Session, form: FormVersion, start: date, end: date) -> list[dict[str, Any]]:
    """FR-PB6: other open versions of the same ministry report whose windows overlap."""
    mrv, report = _parts(db, form)
    others = db.execute(
        select(FormVersion, MinistryReportVersion)
        .join(MinistryReportVersion, MinistryReportVersion.id == FormVersion.ministry_report_version_id)
        .where(
            MinistryReportVersion.ministry_report_id == report.id,
            FormVersion.id != form.id,
            FormVersion.status == "published",
            FormVersion.closed_at.is_(None),
        )
    ).all()
    return [
        {"form_id": f.id, "version_code": v.version_code, "start_date": f.start_date, "end_date": f.end_date}
        for f, v in others
        if f.start_date <= end and start <= f.end_date
    ]


def publish(db: Session, principal: Principal, form_id: int, body: PublishIn) -> FormVersion:
    """FR-PB1 to FR-PB3: publish with D/MM/YYYY dates; the window is inclusive, in district time."""
    _require(principal, REVIEWERS)
    form = _locked(db, form_id, body.version)
    if form.status != "in_review":
        raise AppError(409, "form_not_in_review")
    if body.start_date < _today(db):
        raise invalid("start_in_past")
    if body.end_date < body.start_date:
        raise invalid("end_before_start")
    overlaps = _overlapping(db, form, body.start_date, body.end_date)
    if overlaps and not body.confirm_overlap:
        raise AppError(409, "window_overlap", {"forms": overlaps})
    form.status = "published"
    form.start_date, form.end_date = body.start_date, body.end_date
    form.published_by, form.published_at = principal.user.id, clock.now()
    db.add(FormReviewComment(form_version_id=form.id, author_id=principal.user.id, action="published"))
    db.flush()
    _audit(db, "form.published", form, start=body.start_date, end=body.end_date, overlap_confirmed=bool(overlaps))
    params = _notice_params(db, form)
    for role in (Role.SUPERVISOR, Role.CLUSTER_HEAD):
        notify.notify_role(db, role, "form_published", params)
    db.commit()
    return form


def extend(db: Session, principal: Principal, form_id: int, body: WindowIn) -> FormVersion:
    """FR-PB5: move the end date later. Content never changes after publishing."""
    _require(principal, REVIEWERS)
    form = _locked(db, form_id, body.version)
    if form.status != "published" or form.closed_at is not None:
        raise AppError(409, "form_not_open")
    if body.end_date <= form.end_date:
        raise invalid("end_not_later")
    before = form.end_date
    form.end_date = body.end_date
    db.add(
        FormReviewComment(form_version_id=form.id, author_id=principal.user.id, action="extended", comment=body.reason)
    )
    db.flush()
    _audit(db, "form.window_extended", form, before=before, end=body.end_date, reason=body.reason)
    notify.notify_role(db, Role.SUPERVISOR, "form_window_changed", _notice_params(db, form))
    db.commit()
    return form


def close(db: Session, principal: Principal, form_id: int, body: CloseIn) -> FormVersion:
    _require(principal, REVIEWERS)
    form = _locked(db, form_id, body.version)
    if form.status != "published" or form.effective_status(_today(db)) == "closed":
        raise AppError(409, "form_not_open")
    form.closed_at = clock.now()
    form.close_reason = body.reason
    db.add(
        FormReviewComment(form_version_id=form.id, author_id=principal.user.id, action="closed", comment=body.reason)
    )
    db.flush()
    _audit(db, "form.closed_early", form, reason=body.reason)
    notify.notify_role(db, Role.SUPERVISOR, "form_window_changed", {**_notice_params(db, form), "end": _today(db)})
    db.commit()
    return form


def comments(db: Session, principal: Principal, form_id: int) -> list[dict[str, Any]]:
    _require(principal, (Role.FORM_AUTHOR, Role.DISTRICT_ADMIN))
    get_form(db, principal, form_id)
    rows = db.execute(
        select(FormReviewComment, User)
        .join(User, User.id == FormReviewComment.author_id)
        .where(FormReviewComment.form_version_id == form_id)
        .order_by(FormReviewComment.id)
    ).all()
    return [
        {"action": c.action, "comment": c.comment, "by": u.name, "role": u.role, "at": c.created_at} for c, u in rows
    ]
