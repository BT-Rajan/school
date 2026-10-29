"""A ZIP of scanned reports for a District Admin (FR-RP5).

At most 200 documents per export. It runs as a background job: each report's current version
is watermarked with the admin's name and the time, as when they open it, and a manifest lists
what is inside. The request and the finished export are audited with the document IDs. The ZIP
is stored encrypted like any file, virus checked, and only the admin who asked can download it.
"""

import csv
import io
import re
import zipfile
from datetime import UTC, date
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, jobs
from app.audit import service as audit
from app.auth.deps import Principal
from app.district import get_district
from app.documents import access as documents_access
from app.documents import watermark
from app.errors import AppError, invalid
from app.files import service as files
from app.models import (
    Document,
    DocumentVersion,
    Job,
    MinistryReport,
    MinistryReportVersion,
    Role,
    School,
    StoredFile,
    Supervisor,
    User,
)

MAX_DOCUMENTS = 200
JOB_TYPE = "documents_zip"


class ZipIn(BaseModel):
    document_ids: list[int] | None = Field(default=None, max_length=MAX_DOCUMENTS)
    status: str | None = Field(default=None, max_length=16)
    cluster_id: int | None = None
    school_id: int | None = None
    supervisor_id: int | None = None
    report_version_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None


def _export_rule(_db: Session, principal: Principal, file: StoredFile) -> bool:
    return principal.role == Role.DISTRICT_ADMIN and file.uploaded_by == principal.user.id


files.register_owner("export", _export_rule)


def _matching(db: Session, principal: Principal, body: ZipIn) -> list[int]:
    query = documents_access.visible_query(db, principal).where(
        Document.deleted_at.is_(None), Document.current_version_id.is_not(None)
    )
    if body.document_ids is not None:
        query = query.where(Document.id.in_(body.document_ids))
    if body.status:
        query = query.where(Document.status == body.status)
    if body.cluster_id:
        query = query.where(Document.cluster_id == body.cluster_id)
    if body.school_id:
        query = query.where(Document.school_id == body.school_id)
    if body.supervisor_id:
        query = query.where(Document.owner_supervisor_id == body.supervisor_id)
    if body.report_version_id:
        query = query.where(Document.ministry_report_version_id == body.report_version_id)
    if body.date_from:
        query = query.where(Document.report_date >= body.date_from)
    if body.date_to:
        query = query.where(Document.report_date <= body.date_to)
    return list(
        db.execute(query.with_only_columns(Document.id).order_by(Document.id).limit(MAX_DOCUMENTS + 1)).scalars()
    )


def request_zip(db: Session, principal: Principal, body: ZipIn) -> Job:
    if principal.role != Role.DISTRICT_ADMIN:
        raise AppError(403, "forbidden")
    ids = _matching(db, principal, body)
    if not ids:
        raise invalid("export_empty")
    if len(ids) > MAX_DOCUMENTS:
        raise invalid("export_too_many", {"max": MAX_DOCUMENTS})
    job = jobs.enqueue(db, JOB_TYPE, {"document_ids": ids}, principal.user.id)
    audit.record(
        db,
        "documents.export_requested",
        entity_type="job",
        entity_id=job.id,
        after={
            "document_ids": ids,
            "filters": body.model_dump(mode="json", exclude_none=True, exclude={"document_ids"}),
        },
    )
    db.commit()
    return job


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "x"


@jobs.handler(JOB_TYPE)
def build_zip(db: Session, job: Job) -> dict[str, Any]:
    admin = db.get(User, job.created_by)
    district = get_district(db)
    local = clock.now().replace(tzinfo=UTC).astimezone(ZoneInfo(district.time_zone))
    stamp = f"{local.day}/{local.month:02d}/{local.year} {local.hour:02d}:{local.minute:02d}"
    mark = f"{admin.name} · {admin.staff_id or admin.email} · {stamp}"
    out = io.BytesIO()
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(
        [
            "document_id",
            "file",
            "ministry_report_id",
            "version_id",
            "school_id",
            "school",
            "supervisor",
            "report_date",
            "status",
            "title",
        ]
    )
    included = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for doc_id in job.payload["document_ids"]:
            d = db.get(Document, doc_id)
            # Checked again: a report deleted since the request is left out.
            if d is None or d.deleted_at is not None or d.current_version_id is None:
                continue
            version = db.get(DocumentVersion, d.current_version_id)
            stored = db.get(StoredFile, version.stored_file_id)
            if stored.scan_status != "clean":
                continue
            mrv = db.get(MinistryReportVersion, d.ministry_report_version_id)
            report = db.get(MinistryReport, mrv.ministry_report_id)
            school = db.get(School, d.school_id)
            owner = db.get(User, db.get(Supervisor, d.owner_supervisor_id).user_id)
            parts = (report.report_code, mrv.version_code, school.code, d.report_date.isoformat(), str(d.id))
            name = "_".join(_safe(p) for p in parts) + ".pdf"
            archive.writestr(name, watermark.apply(files.read_content(stored), mark))
            writer.writerow(
                [
                    d.id,
                    name,
                    report.report_code,
                    mrv.version_code,
                    school.code,
                    school.name,
                    owner.name,
                    d.report_date.isoformat(),
                    d.status,
                    d.title,
                ]
            )
            included.append(d.id)
        archive.writestr("manifest.csv", "﻿" + manifest.getvalue())
    content = out.getvalue()
    stored = files.store(
        db,
        admin.id,
        f"reports-{local.strftime('%Y%m%d-%H%M')}.zip",
        content,
        "application/zip",
        None,
        owner_type="export",
        owner_id=job.id,
    )
    audit.record(
        db,
        "documents.exported",
        entity_type="job",
        entity_id=job.id,
        actor_id=admin.id,
        actor_role=Role.DISTRICT_ADMIN.value,
        after={"document_ids": included, "file_id": stored.id, "count": len(included)},
    )
    db.commit()
    return {"file_id": stored.id, "count": len(included), "size": len(content)}


def job_out(db: Session, job: Job) -> dict[str, Any]:
    result = job.result or {}
    file = db.get(StoredFile, result["file_id"]) if result.get("file_id") else None
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "count": result.get("count", len(job.payload.get("document_ids", []))),
        "file": files.file_out(file) if file else None,
        "error": "failed" if job.status == "failed" else None,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


def my_exports(db: Session, principal: Principal) -> list[dict[str, Any]]:
    if principal.role != Role.DISTRICT_ADMIN:
        raise AppError(403, "forbidden")
    rows = db.execute(
        select(Job).where(Job.type == JOB_TYPE, Job.created_by == principal.user.id).order_by(Job.id.desc()).limit(20)
    ).scalars()
    return [job_out(db, j) for j in rows]
