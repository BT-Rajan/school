"""Everything held about one person, for an access request (FR-AD4).

Profile, roles held (teacher, supervisor, Cluster Head), assignments, evaluations by or about
them, requests, scanned report details by or about them, sign-in sessions, notifications and
their audit trail. Secrets are never included: password and code hashes, authenticator
secrets, tokens and file keys. File contents are not included either; each file is listed with
its checksum, and can be supplied from the vault if the request asks for it. The export is
audited with what it contained.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, or_, select
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.errors import not_found
from app.models import (
    AuditLog,
    Cluster,
    Document,
    DocumentVersion,
    Evaluation,
    EvaluationSection,
    Notification,
    NotificationPreference,
    SchoolContact,
    StoredFile,
    Supervisor,
    SupervisorAssignment,
    SupportSession,
    Teacher,
    TeacherRequest,
    TeacherTransfer,
    User,
    UserSession,
)

SECRET_PARTS = ("hash", "secret", "token", "wrapped_key", "storage_key", "csrf")
MAX_AUDIT = 10_000


def _plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row(obj: Any) -> dict[str, Any]:
    out = {}
    for column in inspect(obj).mapper.column_attrs:
        key = column.key
        if any(part in key for part in SECRET_PARTS):
            continue
        out[key] = _plain(getattr(obj, key))
    return out


def _all(db: Session, query) -> list[dict[str, Any]]:
    return [_row(o) for o in db.execute(query).scalars()]


def export(db: Session, user_id: int) -> tuple[bytes, dict[str, int]]:
    user = db.get(User, user_id)
    if user is None:
        raise not_found()
    data: dict[str, Any] = {"exported_at": clock.now().isoformat(), "profile": _row(user)}

    teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
    if teacher:
        data["teacher"] = _row(teacher)
        data["teacher_transfers"] = _all(db, select(TeacherTransfer).where(TeacherTransfer.teacher_id == teacher.id))
        data["contact_teacher_for"] = _all(db, select(SchoolContact).where(SchoolContact.teacher_id == teacher.id))
        data["requests_received"] = _all(db, select(TeacherRequest).where(TeacherRequest.teacher_id == teacher.id))
        data["evaluations_about"] = _all(db, select(Evaluation).where(Evaluation.teacher_id == teacher.id))
        data["documents_about"] = _all(db, select(Document).where(Document.teacher_id == teacher.id))

    supervisor = db.execute(select(Supervisor).where(Supervisor.user_id == user.id)).scalar_one_or_none()
    if supervisor:
        data["supervisor"] = _row(supervisor)
        data["assignments"] = _all(
            db, select(SupervisorAssignment).where(SupervisorAssignment.supervisor_id == supervisor.id)
        )
        evaluations = list(db.execute(select(Evaluation).where(Evaluation.supervisor_id == supervisor.id)).scalars())
        data["evaluations"] = [
            {
                **_row(e),
                "sections": _all(db, select(EvaluationSection).where(EvaluationSection.evaluation_id == e.id)),
            }
            for e in evaluations
        ]
        documents = list(db.execute(select(Document).where(Document.owner_supervisor_id == supervisor.id)).scalars())
        data["documents"] = []
        for d in documents:
            versions = list(db.execute(select(DocumentVersion).where(DocumentVersion.document_id == d.id)).scalars())
            data["documents"].append(
                {
                    **_row(d),
                    "versions": [{**_row(v), "file": _row(db.get(StoredFile, v.stored_file_id))} for v in versions],
                }
            )

    data["clusters_headed"] = _all(db, select(Cluster).where(Cluster.cluster_head_id == user.id))
    data["requests_sent"] = _all(db, select(TeacherRequest).where(TeacherRequest.requested_by == user.id))
    data["uploaded_files"] = _all(db, select(StoredFile).where(StoredFile.uploaded_by == user.id))
    data["sessions"] = _all(db, select(UserSession).where(UserSession.user_id == user.id))
    data["notifications"] = _all(db, select(Notification).where(Notification.user_id == user.id))
    data["notification_preferences"] = _all(
        db, select(NotificationPreference).where(NotificationPreference.user_id == user.id)
    )
    data["support_views"] = _all(db, select(SupportSession).where(SupportSession.user_id == user.id))
    data["audit_trail"] = _all(
        db,
        select(AuditLog)
        .where(
            or_(
                AuditLog.actor_id == user.id,
                (AuditLog.entity_type == "user") & (AuditLog.entity_id == str(user.id)),
            )
        )
        .order_by(AuditLog.seq.desc())
        .limit(MAX_AUDIT),
    )
    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode(), counts


def export_and_audit(db: Session, user_id: int) -> bytes:
    content, counts = export(db, user_id)
    audit.record(
        db, "person.exported", entity_type="user", entity_id=user_id, severity="warning", after={"contents": counts}
    )
    db.commit()
    return content
