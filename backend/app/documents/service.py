"""Scanned report vault: upload, submit, review, forward, and keep (section 9).

Every read goes through access.visible_query; every action is audited
(FR-D55). Files live in the file service: encrypted, scanned, and served only
through session-bound links, watermarked for anyone but the owner.
"""

import io
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pikepdf
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.assignments import queries as assignments
from app.audit import service as audit
from app.auth.deps import Principal
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.files import service as files
from app.forms import service as forms
from app.models import (
    AuditLog,
    Cluster,
    Document,
    DocumentForward,
    DocumentVersion,
    Evaluation,
    FormVersion,
    MinistryReport,
    MinistryReportVersion,
    Role,
    School,
    StoredFile,
    Supervisor,
    Teacher,
    TeacherTransfer,
    User,
)
from app.notifications import service as notify
from app.structure.service import paginate

from . import access, watermark

EDITABLE = ("draft", "withdrawn", "returned")
UNDER_REVIEW = ("submitted", "viewed")


class CreateIn(BaseModel):
    file_ids: list[int] = Field(min_length=1, max_length=50)
    ministry_report_version_id: int
    school_id: int
    report_date: date
    title: str | None = Field(default=None, max_length=300)
    teacher_id: int | None = None
    evaluation_id: int | None = None
    notes: str | None = Field(default=None, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    client_key: str | None = Field(default=None, max_length=64)
    device_time: datetime | None = None
    confirm_duplicate: bool = False


class UpdateIn(BaseModel):
    version: int
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=20)
    report_date: date | None = None
    teacher_id: int | None = None
    evaluation_id: int | None = None


class NewVersionIn(BaseModel):
    version: int
    file_ids: list[int] = Field(min_length=1, max_length=50)
    reason: str | None = Field(default=None, max_length=1000)
    client_key: str | None = Field(default=None, max_length=64)


class VersionIn(BaseModel):
    version: int


class SubmitIn(VersionIn):
    message: str | None = Field(default=None, max_length=1000)


class ReviewIn(VersionIn):
    comment: str | None = Field(default=None, max_length=5000)


class ReturnIn(VersionIn):
    comment: str = Field(min_length=1, max_length=5000)


class ForwardIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class LinkIn(BaseModel):
    disposition: Literal["inline", "attachment"] = "inline"
    version_id: int | None = None


def _today(db: Session) -> date:
    return clock.local_date(get_district(db).time_zone)


def _own(db: Session, principal: Principal) -> Supervisor:
    if principal.role != Role.SUPERVISOR:
        raise AppError(403, "forbidden")
    supervisor = assignments.supervisor_for_user(db, principal.user.id)
    if supervisor is None:
        raise AppError(403, "forbidden")
    return supervisor


def _require_admin(principal: Principal) -> None:
    if principal.role != Role.DISTRICT_ADMIN:
        raise AppError(403, "forbidden")


def _audit(db: Session, action: str, d: Document, severity: str = "info", **after: Any) -> None:
    audit.record(
        db,
        action,
        entity_type="document",
        entity_id=d.id,
        cluster_id=d.cluster_id,
        after=after or None,
        severity=severity,
    )


# File access: documents are served only to those who may see them, watermarked
# for everyone except the owner (FR-D13, FR-D27).


def _file_rule(db: Session, principal: Principal, file: StoredFile) -> bool:
    version = db.get(DocumentVersion, file.owner_id)
    return version is not None and access.can_access(db, principal, version.document_id)


def _file_transform(db: Session, principal: Principal, file: StoredFile, content: bytes) -> bytes:
    version = db.get(DocumentVersion, file.owner_id)
    document = db.get(Document, version.document_id)
    if access.is_owner(db, principal, document):
        return content
    user = principal.user
    local = clock.now().replace(tzinfo=UTC).astimezone(ZoneInfo(get_district(db).time_zone))
    stamp = f"{local.day}/{local.month:02d}/{local.year} {local.hour:02d}:{local.minute:02d}"
    return watermark.apply(content, f"{user.name} · {user.staff_id or user.email} · {stamp}")


files.register_owner("document", _file_rule, _file_transform)


# Output ----------------------------------------------------------------------------


def _name(db: Session, user_id: int | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.name if user else None


def document_out(db: Session, principal: Principal, d: Document, *, full: bool = False) -> dict[str, Any]:
    mrv = db.get(MinistryReportVersion, d.ministry_report_version_id)
    report = db.get(MinistryReport, mrv.ministry_report_id)
    school = db.get(School, d.school_id)
    owner = db.get(Supervisor, d.owner_supervisor_id)
    version = db.get(DocumentVersion, d.current_version_id) if d.current_version_id else None
    file = db.get(StoredFile, version.stored_file_id) if version else None
    overdue_days = int(get_district(db).setting("acknowledge_overdue_days"))
    out: dict[str, Any] = {
        "id": d.id,
        "title": d.title,
        "report": {
            "code": report.report_code,
            "version_code": mrv.version_code,
            "version_id": mrv.id,
            "title_en": mrv.title_en,
            "title_ar": mrv.title_ar,
        },
        "school": {"id": school.id, "code": school.code, "name": school.name},
        "cluster_id": d.cluster_id,
        "teacher_id": d.teacher_id,
        "evaluation_id": d.evaluation_id,
        "supervisor": {"id": owner.id, "name": _name(db, owner.user_id)},
        "report_date": d.report_date,
        "status": "deleted" if d.deleted_at else d.status,
        "submitted_at": d.submitted_at,
        "first_viewed_at": d.first_viewed_at,
        "acknowledged_at": d.acknowledged_at,
        "returned_at": d.returned_at,
        "review_comment": d.review_comment,
        "archived": d.archived_at is not None,
        "overdue": d.status in UNDER_REVIEW
        and d.submitted_at is not None
        and clock.now() - d.submitted_at > timedelta(days=overdue_days),
        "retention_expired": d.retention_until < _today(db),
        "file": {"status": file.scan_status, "pages": file.page_count, "size": file.size} if file else None,
        "mine": access.is_owner(db, principal, d),
        "version": d.version,
    }
    if full:
        out["notes"] = d.notes
        out["tags"] = d.tags
        out["acknowledged_by"] = _name(db, d.acknowledged_by)
        out["returned_by"] = _name(db, d.returned_by)
        out["first_viewed_by"] = _name(db, d.first_viewed_by)
        versions = db.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == d.id).order_by(DocumentVersion.version_no)
        ).scalars()
        out["versions"] = [
            {
                "id": v.id,
                "number": v.version_no,
                "reason": v.reason,
                "created_at": v.created_at,
                "current": v.id == d.current_version_id,
            }
            for v in versions
        ]
        if principal.role == Role.DISTRICT_ADMIN:
            forwards = db.execute(
                select(DocumentForward).where(DocumentForward.document_id == d.id).order_by(DocumentForward.id)
            ).scalars()
            out["forwards"] = [
                {
                    "id": f.id,
                    "cluster_id": f.cluster_id,
                    "note": f.note,
                    "by": _name(db, f.forwarded_by),
                    "at": f.forwarded_at,
                    "revoked_at": f.revoked_at,
                }
                for f in forwards
            ]
    return out


# Building the file -----------------------------------------------------------------------


def _combine(db: Session, principal: Principal, file_ids: list[int]) -> StoredFile:
    """FR-D2: one PDF from the supervisor's own uploads, in the order given."""
    sources = []
    for file_id in file_ids:
        file = db.get(StoredFile, file_id)
        if (
            file is None
            or file.uploaded_by != principal.user.id
            or file.owner_type != "upload"
            or file.deleted_at is not None
            or file.scan_status == "quarantined"
        ):
            raise invalid("file_not_usable", {"file_id": file_id})
        sources.append(file)
    if len(set(file_ids)) != len(file_ids):
        raise invalid("file_not_usable")
    max_pages = int(get_district(db).setting("upload_max_pages"))
    if len(sources) == 1 and sources[0].mime_type == "application/pdf":
        return sources[0]
    combined = pikepdf.new()
    for file in sources:
        content = files.read_content(file)
        if file.mime_type == "application/pdf":
            with pikepdf.open(io.BytesIO(content)) as part:
                combined.pages.extend(part.pages)
        else:
            image = Image.open(io.BytesIO(content)).convert("RGB")
            page = io.BytesIO()
            image.save(page, "PDF", resolution=200)
            with pikepdf.open(io.BytesIO(page.getvalue())) as part:
                combined.pages.extend(part.pages)
        if len(combined.pages) > max_pages:
            raise invalid("too_many_pages", {"max": max_pages})
    out = io.BytesIO()
    combined.save(out, deterministic_id=True)
    for file in sources:
        # The parts live on inside the combined file; drop them so storage is not counted twice.
        file.deleted_at = clock.now()
    name = sources[0].original_name.rsplit(".", 1)[0] + ".pdf"
    return files.store(db, principal.user.id, name, out.getvalue(), "application/pdf", len(combined.pages))


def _add_version(
    db: Session,
    principal: Principal,
    d: Document,
    file_ids: list[int],
    reason: str | None,
    client_key: str | None,
    device_time: datetime | None = None,
) -> DocumentVersion:
    file = _combine(db, principal, file_ids)
    number = (
        db.execute(select(func.max(DocumentVersion.version_no)).where(DocumentVersion.document_id == d.id)).scalar_one()
        or 0
    ) + 1
    version = DocumentVersion(
        document_id=d.id,
        version_no=number,
        stored_file_id=file.id,
        reason=reason,
        client_key=client_key,
        device_time=device_time,
        created_by=principal.user.id,
    )
    db.add(version)
    db.flush()
    file.owner_type, file.owner_id = "document", version.id
    d.current_version_id = version.id
    return version


# Rules -------------------------------------------------------------------------------------


def _teacher_school_on(db: Session, teacher: Teacher, day: date) -> int:
    """The teacher's school on a date, from the transfer history (FR-D5)."""
    later = db.execute(
        select(TeacherTransfer)
        .where(TeacherTransfer.teacher_id == teacher.id, TeacherTransfer.moved_on > day)
        .order_by(TeacherTransfer.moved_on)
        .limit(1)
    ).scalar_one_or_none()
    return later.from_school_id if later else teacher.school_id


def _check_links(db: Session, own: Supervisor, d: Document, report: MinistryReport) -> None:
    if d.report_date > _today(db):
        raise invalid("report_date_in_future")
    if not assignments.date_in_window(db, own.id, d.school_id, d.report_date):
        raise invalid("report_date_outside_assignment")
    if report.subject_type == "teacher":
        teacher = db.get(Teacher, d.teacher_id) if d.teacher_id else None
        if teacher is None:
            raise invalid("teacher_required")
        if _teacher_school_on(db, teacher, d.report_date) != d.school_id:
            raise invalid("teacher_not_at_school")
    elif d.teacher_id is not None:
        teacher = db.get(Teacher, d.teacher_id)
        if teacher is None or _teacher_school_on(db, teacher, d.report_date) != d.school_id:
            raise invalid("teacher_not_at_school")
    if d.evaluation_id is not None:
        # FR-E11: only the supervisor's own evaluation of the same school.
        e = db.get(Evaluation, d.evaluation_id)
        if e is None or e.supervisor_id != own.id or e.school_id != d.school_id:
            raise invalid("evaluation_not_linkable")


def _locked(db: Session, principal: Principal, document_id: int, version: int) -> Document:
    access.get_visible(db, principal, document_id)
    d = db.execute(
        select(Document).where(Document.id == document_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    if d.version != version:
        raise AppError(409, "version_conflict", {"current": document_out(db, principal, d)})
    return d


def _locked_own(db: Session, principal: Principal, document_id: int, version: int) -> Document:
    _own(db, principal)
    d = _locked(db, principal, document_id, version)
    if not access.is_owner(db, principal, d):
        raise AppError(403, "forbidden")
    return d


def _params(db: Session, d: Document) -> dict[str, Any]:
    mrv = db.get(MinistryReportVersion, d.ministry_report_version_id)
    report = db.get(MinistryReport, mrv.ministry_report_id)
    school = db.get(School, d.school_id)
    owner = db.get(Supervisor, d.owner_supervisor_id)
    return {
        "report_code": report.report_code,
        "school": school.name,
        "supervisor": _name(db, owner.user_id),
        "document_id": d.id,
    }


def _add_years(day: date, years: int) -> date:
    """FR-D32: kept at least this long from the report date. 29 February becomes 28 February."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


# Supervisor actions -------------------------------------------------------------------------


def create(db: Session, principal: Principal, body: CreateIn) -> Document:
    own = _own(db, principal)
    if body.client_key:
        # FR-D6: a retried upload creates the document once.
        existing = db.execute(
            select(Document)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(Document.owner_supervisor_id == own.id, DocumentVersion.client_key == body.client_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    mrv, report, _form = forms.published_version(db, body.ministry_report_version_id)
    school = db.get(School, body.school_id)
    if school is None or school.id not in assignments.school_ids_for_supervisor(db, own.id):
        audit.record_denial(
            "document.create", entity_type="school", entity_id=body.school_id, reason="scope", request_db=db
        )
        raise not_found()
    district = get_district(db)
    years = int(district.setting("document_retention_years"))
    d = Document(
        owner_supervisor_id=own.id,
        cluster_id=school.cluster_id,
        school_id=school.id,
        teacher_id=body.teacher_id,
        evaluation_id=body.evaluation_id,
        ministry_report_version_id=mrv.id,
        title=(
            body.title or (mrv.title_ar if principal.user.locale == "ar" else mrv.title_en) or report.report_code
        ).strip(),
        report_date=body.report_date,
        notes=body.notes,
        tags=[t.strip()[:50] for t in body.tags if t.strip()],
        retention_until=_add_years(body.report_date, years),
    )
    _check_links(db, own, d, report)
    db.add(d)
    db.flush()
    try:
        version = _add_version(db, principal, d, body.file_ids, None, body.client_key, body.device_time)
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "duplicate_client_key") from exc
    file = db.get(StoredFile, version.stored_file_id)
    if not body.confirm_duplicate:
        # FR-D7: warn when the same file is already one of the owner's documents.
        duplicate = db.execute(
            select(Document.id)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .join(StoredFile, StoredFile.id == DocumentVersion.stored_file_id)
            .where(
                Document.owner_supervisor_id == own.id,
                Document.id != d.id,
                StoredFile.sha256 == file.sha256,
                Document.deleted_at.is_(None),
            )
        ).first()
        if duplicate:
            db.rollback()
            raise AppError(409, "duplicate_document", {"document_id": duplicate[0]})
    if body.device_time and abs(body.device_time - clock.now()) > timedelta(hours=24):
        audit.record(
            db,
            "document.clock_skew",
            entity_type="document",
            entity_id=d.id,
            severity="warning",
            after={"device_time": body.device_time},
        )
    _audit(
        db, "document.uploaded", d, file_id=file.id, sha256=file.sha256, pages=file.page_count, report_version_id=mrv.id
    )
    db.commit()
    return d


def update(db: Session, principal: Principal, document_id: int, body: UpdateIn) -> Document:
    d = _locked_own(db, principal, document_id, body.version)
    if d.status not in EDITABLE:
        raise AppError(409, "document_locked")
    own = _own(db, principal)
    before = {
        "title": d.title,
        "notes": d.notes,
        "tags": d.tags,
        "report_date": d.report_date,
        "teacher_id": d.teacher_id,
        "evaluation_id": d.evaluation_id,
    }
    for field in ("title", "notes", "tags", "report_date"):
        value = getattr(body, field)
        if value is not None:
            setattr(d, field, value)
    for field in ("teacher_id", "evaluation_id"):
        if field in body.model_fields_set:
            setattr(d, field, getattr(body, field))
    mrv = db.get(MinistryReportVersion, d.ministry_report_version_id)
    _check_links(db, own, d, db.get(MinistryReport, mrv.ministry_report_id))
    after = {
        "title": d.title,
        "notes": d.notes,
        "tags": d.tags,
        "report_date": d.report_date,
        "teacher_id": d.teacher_id,
        "evaluation_id": d.evaluation_id,
    }
    old, new = audit.changed_fields(before, after)
    d.updated_at = clock.now()
    db.flush()
    if new:
        audit.record(
            db,
            "document.metadata_edited",
            entity_type="document",
            entity_id=d.id,
            cluster_id=d.cluster_id,
            before={k: v for k, v in old.items() if k not in ("title", "notes")},
            after={k: v for k, v in new.items() if k not in ("title", "notes")},
        )
    db.commit()
    return d


def new_version(db: Session, principal: Principal, document_id: int, body: NewVersionIn) -> Document:
    """FR-D23, FR-D24: a returned or draft report gets a new file; an acknowledged one needs a reason."""
    d = _locked_own(db, principal, document_id, body.version)
    if d.status in UNDER_REVIEW:
        raise AppError(409, "document_under_review")
    correction = d.status == "acknowledged"
    if correction and not (body.reason or "").strip():
        raise invalid("reason_required")
    version = _add_version(db, principal, d, body.file_ids, body.reason, body.client_key)
    if correction:
        # A correction goes back for review; the acknowledged version stays visible.
        d.status, d.submitted_at = "submitted", clock.now()
        notify.notify_role(db, Role.DISTRICT_ADMIN, "report_submitted", _params(db, d))
    d.updated_at = clock.now()
    db.flush()
    _audit(db, "document.new_version", d, number=version.version_no, reason=body.reason, correction=correction)
    db.commit()
    return d


def submit(db: Session, principal: Principal, document_id: int, body: SubmitIn) -> Document:
    """FR-D20: to the District Admins, who are all notified."""
    d = _locked_own(db, principal, document_id, body.version)
    if d.status not in EDITABLE:
        raise AppError(409, "document_not_submittable")
    d.status, d.submitted_at = "submitted", clock.now()
    d.review_comment = None
    db.flush()
    _audit(db, "document.submitted", d, message=bool(body.message))
    notify.notify_role(db, Role.DISTRICT_ADMIN, "report_submitted", _params(db, d))
    db.commit()
    return d


def withdraw(db: Session, principal: Principal, document_id: int, body: VersionIn) -> Document:
    """FR-D24: possible until an admin acknowledges it."""
    d = _locked_own(db, principal, document_id, body.version)
    if d.status not in UNDER_REVIEW:
        raise AppError(409, "document_not_withdrawable")
    d.status = "withdrawn"
    db.flush()
    _audit(db, "document.withdrawn", d)
    notify.notify_role(db, Role.DISTRICT_ADMIN, "report_withdrawn", _params(db, d))
    db.commit()
    return d


def delete(db: Session, principal: Principal, document_id: int, body: VersionIn) -> Document:
    """FR-D30: a soft delete of an unsubmitted report; admins still see it and can restore it."""
    d = _locked_own(db, principal, document_id, body.version)
    if d.status not in ("draft", "withdrawn"):
        raise AppError(409, "document_not_deletable")
    d.deleted_at, d.deleted_by = clock.now(), principal.user.id
    db.flush()
    _audit(db, "document.deleted", d)
    db.commit()
    return d


# Admin actions ---------------------------------------------------------------------------


def acknowledge(db: Session, principal: Principal, document_id: int, body: ReviewIn) -> Document:
    _require_admin(principal)
    d = _locked(db, principal, document_id, body.version)
    if d.status not in UNDER_REVIEW or d.deleted_at:
        raise AppError(409, "document_not_under_review")
    d.status, d.acknowledged_at, d.acknowledged_by = "acknowledged", clock.now(), principal.user.id
    d.review_comment = body.comment
    db.flush()
    _audit(db, "document.acknowledged", d, comment=bool(body.comment))
    owner = db.get(Supervisor, d.owner_supervisor_id)
    notify.notify(db, owner.user_id, "report_acknowledged", _params(db, d))
    db.commit()
    return d


def return_(db: Session, principal: Principal, document_id: int, body: ReturnIn) -> Document:
    _require_admin(principal)
    d = _locked(db, principal, document_id, body.version)
    if d.status not in UNDER_REVIEW or d.deleted_at:
        raise AppError(409, "document_not_under_review")
    d.status, d.returned_at, d.returned_by, d.review_comment = "returned", clock.now(), principal.user.id, body.comment
    db.flush()
    _audit(db, "document.returned", d)
    owner = db.get(Supervisor, d.owner_supervisor_id)
    notify.notify(db, owner.user_id, "report_returned", {**_params(db, d), "comment": body.comment[:200]})
    db.commit()
    return d


def forward(db: Session, principal: Principal, document_id: int, body: ForwardIn) -> Document:
    """FR-D25: view-only, to the Cluster Head of the document's cluster. Never to supervisors or teachers."""
    _require_admin(principal)
    d = access.get_visible(db, principal, document_id)
    if d.status not in ("submitted", "viewed", "acknowledged") or d.deleted_at:
        raise AppError(409, "document_not_forwardable")
    cluster = db.get(Cluster, d.cluster_id)
    if cluster.cluster_head_id is None:
        raise invalid("cluster_has_no_head")
    active = db.execute(
        select(DocumentForward).where(DocumentForward.document_id == d.id, DocumentForward.revoked_at.is_(None))
    ).scalar_one_or_none()
    if active is None:
        db.add(DocumentForward(document_id=d.id, cluster_id=cluster.id, note=body.note, forwarded_by=principal.user.id))
        db.flush()
        _audit(db, "document.forwarded", d, cluster_id=cluster.id)
        notify.notify(db, cluster.cluster_head_id, "report_forwarded", _params(db, d))
    db.commit()
    return d


def revoke_forward(db: Session, principal: Principal, document_id: int) -> Document:
    _require_admin(principal)
    d = access.get_visible(db, principal, document_id)
    active = db.execute(
        select(DocumentForward).where(DocumentForward.document_id == d.id, DocumentForward.revoked_at.is_(None))
    ).scalar_one_or_none()
    if active is not None:
        active.revoked_at, active.revoked_by = clock.now(), principal.user.id
        db.flush()
        _audit(db, "document.forward_revoked", d)
    db.commit()
    return d


def restore(db: Session, principal: Principal, document_id: int) -> Document:
    _require_admin(principal)
    d = access.get_visible(db, principal, document_id)
    if d.deleted_at is None:
        raise AppError(409, "document_not_deleted")
    d.deleted_at, d.deleted_by = None, None
    db.flush()
    _audit(db, "document.restored", d)
    db.commit()
    return d


def archive(db: Session, principal: Principal, document_id: int) -> Document:
    """FR-D31: acknowledged reports leave the inbox and stay searchable."""
    _require_admin(principal)
    d = access.get_visible(db, principal, document_id)
    if d.status != "acknowledged":
        raise AppError(409, "document_not_acknowledged")
    d.archived_at = d.archived_at or clock.now()
    db.flush()
    _audit(db, "document.archived", d)
    db.commit()
    return d


# Viewing ----------------------------------------------------------------------------------


def link(db: Session, principal: Principal, document_id: int, body: LinkIn) -> files.Link:
    """Open a version of the file. The first admin view moves the report to Viewed (FR-D21)."""
    d = access.get_visible(db, principal, document_id)
    version_id = body.version_id or d.current_version_id
    version = db.get(DocumentVersion, version_id)
    if version is None or version.document_id != d.id:
        raise not_found()
    result = files.create_link(db, principal, version.stored_file_id, body.disposition)
    d = db.execute(select(Document).where(Document.id == d.id).with_for_update()).scalar_one()
    if not access.is_owner(db, principal, d):
        if principal.role == Role.DISTRICT_ADMIN and d.status == "submitted":
            d.status = "viewed"
        if principal.role == Role.DISTRICT_ADMIN and d.first_viewed_at is None:
            d.first_viewed_at, d.first_viewed_by = clock.now(), principal.user.id
    db.flush()
    _audit(
        db, "document.viewed" if body.disposition == "inline" else "document.downloaded", d, version=version.version_no
    )
    db.commit()
    return result


def access_history(db: Session, principal: Principal, document_id: int) -> list[dict[str, Any]]:
    """FR-L9: who viewed or downloaded the report, and when. For its owner and admins."""
    d = access.get_visible(db, principal, document_id)
    if not (access.is_owner(db, principal, d) or principal.role == Role.DISTRICT_ADMIN):
        raise AppError(403, "forbidden")
    owner_user = db.get(Supervisor, d.owner_supervisor_id).user_id
    rows = db.execute(
        select(AuditLog, User)
        .join(User, User.id == AuditLog.actor_id)
        .where(
            AuditLog.entity_type == "document",
            AuditLog.entity_id == str(d.id),
            AuditLog.action.in_(("document.viewed", "document.downloaded")),
            AuditLog.actor_id != owner_user,
        )
        .order_by(AuditLog.seq.desc())
    ).all()
    return [
        {"action": a.action.removeprefix("document."), "by": u.name, "role": u.role, "at": a.created_at}
        for a, u in rows
    ]


# Lists ------------------------------------------------------------------------------------


def list_documents(
    db: Session,
    principal: Principal,
    *,
    q: str | None = None,
    status: str | None = None,
    supervisor_id: int | None = None,
    cluster_id: int | None = None,
    school_id: int | None = None,
    report_code: str | None = None,
    report_version_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_archived: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """My reports, the admin inbox, and Forwarded to me: one scoped query (FR-D40 to FR-D43)."""
    query = access.visible_query(db, principal)
    if status == "deleted":
        query = query.where(Document.deleted_at.is_not(None))
    elif status:
        query = query.where(Document.status == status, Document.deleted_at.is_(None))
    elif principal.role == Role.DISTRICT_ADMIN:
        query = query.where(Document.deleted_at.is_(None))
    if principal.role == Role.DISTRICT_ADMIN and status is None:
        # The inbox shows submitted work; drafts are in progress and listed on request.
        query = query.where(Document.status != "draft")
    if not include_archived:
        query = query.where(Document.archived_at.is_(None))
    if q:
        # Metadata only (FR-D42). The column collation ignores case and Latin accents.
        term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(Document.title.like(term), Document.notes.like(term)))
    if supervisor_id:
        query = query.where(Document.owner_supervisor_id == supervisor_id)
    if cluster_id:
        query = query.where(Document.cluster_id == cluster_id)
    if school_id:
        query = query.where(Document.school_id == school_id)
    if report_version_id:
        query = query.where(Document.ministry_report_version_id == report_version_id)
    if report_code:
        query = (
            query.join(MinistryReportVersion, MinistryReportVersion.id == Document.ministry_report_version_id)
            .join(MinistryReport, MinistryReport.id == MinistryReportVersion.ministry_report_id)
            .where(MinistryReport.report_code == report_code)
        )
    if date_from:
        query = query.where(Document.report_date >= date_from)
    if date_to:
        query = query.where(Document.report_date <= date_to)
    # Unacknowledged and returned work first, then newest.
    priority = Document.status.in_(("submitted", "viewed", "returned", "draft"))
    query = query.order_by(priority.desc(), Document.submitted_at.desc(), Document.id.desc())
    rows, total = paginate(db, query, page, page_size)
    return {"items": [document_out(db, principal, d) for (d,) in rows], "total": total, "page": page}


def supervisor_dashboard(db: Session, principal: Principal) -> dict[str, Any]:
    """FR-D44: the supervisor's own reports, returns, coverage and monthly submissions."""
    own = _own(db, principal)
    mine = list(db.execute(access.visible_query(db, principal)).scalars())
    counts = Counter(d.status for d in mine)
    returned = [document_out(db, principal, d) for d in mine if d.status == "returned"]
    today = _today(db)
    school_ids = assignments.school_ids_for_supervisor(db, own.id, today)
    schools = {s.id: s for s in db.execute(select(School).where(School.id.in_(school_ids))).scalars()}
    active_forms = [
        f
        for f in db.execute(select(FormVersion).where(FormVersion.status == "published")).scalars()
        if f.effective_status(today) == "active"
    ]
    submitted = {
        (d.school_id, d.ministry_report_version_id) for d in mine if d.status in ("submitted", "viewed", "acknowledged")
    }
    coverage = []
    for form in active_forms:
        mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
        report = db.get(MinistryReport, mrv.ministry_report_id)
        coverage.append(
            {
                "report": {
                    "code": report.report_code,
                    "version_code": mrv.version_code,
                    "version_id": mrv.id,
                    "title_en": mrv.title_en,
                    "title_ar": mrv.title_ar,
                },
                "schools": [
                    {"id": s.id, "code": s.code, "name": s.name, "covered": (s.id, mrv.id) in submitted}
                    for s in sorted(schools.values(), key=lambda s: s.code)
                ],
            }
        )
    months = Counter(d.submitted_at.strftime("%Y-%m") for d in mine if d.submitted_at)
    history = []
    for d in mine:
        for entry in access_history(db, principal, d.id):
            history.append({"document_id": d.id, "title": d.title, **entry})
    history.sort(key=lambda h: h["at"], reverse=True)
    return {
        "counts": {
            s: counts.get(s, 0) for s in ("draft", "submitted", "viewed", "acknowledged", "returned", "withdrawn")
        },
        "returned": returned,
        "coverage": coverage,
        "per_month": [{"month": m, "count": c} for m, c in sorted(months.items())],
        "access_history": history[:50],
    }


def linked_documents(db: Session, principal: Principal, evaluation_id: int) -> list[dict[str, Any]]:
    """FR-E11: documents linked to an evaluation that this viewer may see."""
    rows = db.execute(access.visible_query(db, principal).where(Document.evaluation_id == evaluation_id)).scalars()
    return [document_out(db, principal, d) for d in rows]
