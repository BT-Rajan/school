"""The audit viewer (FR-L5): search and filter by actor, entity, action and date, and export,
which is itself audited.

Entries store user IDs, not names (FR-L6); the viewer looks names up for display only. Entries
older than the audit retention period are counted for admin review and never removed (13.1).
"""

import csv
import io
import json
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.district import get_district, local_midnight_utc
from app.errors import invalid
from app.models import AuditLog, User
from app.reporting import render
from app.reporting.reports import Column, Report

MAX_EXPORT = 100_000


class AuditFilters(BaseModel):
    actor_id: int | None = None
    action: str | None = Field(default=None, max_length=80)  # an exact action, or a prefix ending in "."
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: str | None = Field(default=None, max_length=64)
    severity: str | None = Field(default=None, pattern="^(info|warning|critical)$")
    date_from: date | None = None
    date_to: date | None = None


def _query(db: Session, f: AuditFilters) -> Select:
    query = select(AuditLog)
    if f.actor_id is not None:
        query = query.where(AuditLog.actor_id == f.actor_id)
    if f.action:
        query = query.where(
            AuditLog.action.startswith(f.action) if f.action.endswith(".") else AuditLog.action == f.action
        )
    if f.entity_type:
        query = query.where(AuditLog.entity_type == f.entity_type)
    if f.entity_id:
        query = query.where(AuditLog.entity_id == f.entity_id)
    if f.severity:
        query = query.where(AuditLog.severity == f.severity)
    district = get_district(db)
    if f.date_from and f.date_to and f.date_from > f.date_to:
        raise invalid("filter_dates_reversed")
    # Dates are the district's days.
    if f.date_from:
        query = query.where(AuditLog.created_at >= local_midnight_utc(district, f.date_from))
    if f.date_to:
        query = query.where(AuditLog.created_at < local_midnight_utc(district, f.date_to + timedelta(days=1)))
    return query


def _names(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {u.id: u.name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()}


def entry_out(e: AuditLog, names: dict[int, str]) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "at": e.created_at,
        "actor": {"id": e.actor_id, "name": names.get(e.actor_id)} if e.actor_id else None,
        "actor_role": e.actor_role,
        "cluster_id": e.cluster_id,
        "action": e.action,
        "severity": e.severity,
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "before": e.before,
        "after": e.after,
        "ip": e.ip,
        "user_agent": e.user_agent,
        "hash": e.hash,
    }


def search(db: Session, f: AuditFilters, page: int, page_size: int) -> dict[str, Any]:
    query = _query(db, f)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = list(
        db.execute(query.order_by(AuditLog.seq.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    )
    names = _names(db, {e.actor_id for e in rows if e.actor_id})
    years = int(get_district(db).setting("audit_retention_years"))
    now = clock.now()
    try:
        cutoff = now.replace(year=now.year - years)
    except ValueError:  # 29 February
        cutoff = now.replace(year=now.year - years, day=28)
    past_retention = db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.created_at < cutoff)
    ).scalar_one()
    return {
        "items": [entry_out(e, names) for e in rows],
        "total": total,
        "page": page,
        "retention_years": years,
        "past_retention": past_retention,
        "actions": sorted(db.execute(select(AuditLog.action).distinct()).scalars()),
    }


COLUMNS = [
    Column("seq", "Sequence", "التسلسل"),
    Column("at", "Time (UTC)", "الوقت (UTC)"),
    Column("actor_id", "Actor ID", "رقم المنفّذ"),
    Column("actor", "Actor", "المنفّذ"),
    Column("actor_role", "Role", "الدور"),
    Column("action", "Action", "الإجراء"),
    Column("severity", "Severity", "الأهمية"),
    Column("entity_type", "Entity", "الكيان"),
    Column("entity_id", "Entity ID", "رقم الكيان"),
    Column("before", "Before", "قبل"),
    Column("after", "After", "بعد"),
    Column("ip", "IP address", "عنوان IP"),
    Column("hash", "Entry hash", "بصمة القيد"),
]


def export(db: Session, f: AuditFilters, fmt: str, locale: str, by: User) -> tuple[bytes, str]:
    query = _query(db, f).order_by(AuditLog.seq)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    if total > MAX_EXPORT:
        raise invalid("export_too_many", {"max": MAX_EXPORT})
    entries = list(db.execute(query).scalars())
    names = _names(db, {e.actor_id for e in entries if e.actor_id})
    rows = [
        [
            e.seq,
            e.created_at.isoformat(timespec="seconds"),
            e.actor_id,
            names.get(e.actor_id, ""),
            e.actor_role,
            e.action,
            e.severity,
            e.entity_type,
            e.entity_id,
            json.dumps(e.before, ensure_ascii=False) if e.before else "",
            json.dumps(e.after, ensure_ascii=False) if e.after else "",
            e.ip,
            e.hash,
        ]
        for e in entries
    ]
    shown = f.model_dump(mode="json", exclude_none=True)
    # FR-L5: exporting the audit log is itself audited, before the file leaves.
    audit.record(db, "audit.exported", entity_type="audit", after={"format": fmt, "filters": shown, "rows": len(rows)})
    db.commit()
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([c.label(locale) for c in COLUMNS])
        writer.writerows(rows)
        return ("﻿" + out.getvalue()).encode(), "text/csv; charset=utf-8"
    report = Report("audit_log", "Audit log", "سجل التدقيق", COLUMNS, rows)
    filters = render.filter_text(shown, {}, locale)
    made = render.WORDS[locale]["made"].format(name=by.name, at=render.stamp(get_district(db).time_zone))
    return render.to_xlsx(
        report, locale, filters, made
    ), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
