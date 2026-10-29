"""Hash-chained audit log (FR-L1 to FR-L4).

Every entry is written in the same transaction as the change it records, so
a change and its audit entry commit or roll back together. Permission
denials are the exception: the request fails, so they are written in their
own transaction.
"""

import enum
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, context
from app.db import session_factory
from app.models import AuditChainHead, AuditLog, AuditVerification

GENESIS_HASH = "0" * 64
HEAD_ID = 1


def jsonable(value: Any) -> Any:
    """Normalize values so the stored JSON is exactly what was hashed."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(v) for v in value]
    if isinstance(value, enum.Enum):
        return jsonable(value.value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal | float):
        return str(value)
    return value


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep only the fields that changed (FR-L6)."""
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def _canonical(entry: dict[str, Any]) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def compute_hash(row: AuditLog) -> str:
    entry = {
        "seq": row.seq,
        "actor_id": row.actor_id,
        "actor_role": row.actor_role,
        "cluster_id": row.cluster_id,
        "action": row.action,
        "severity": row.severity,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "before": row.before,
        "after": row.after,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "request_id": row.request_id,
        "created_at": row.created_at.isoformat(),
        "prev_hash": row.prev_hash,
    }
    return hashlib.sha256(_canonical(entry)).hexdigest()


def ensure_head(db: Session) -> None:
    if db.get(AuditChainHead, HEAD_ID) is None:
        db.add(AuditChainHead(id=HEAD_ID, last_seq=0, last_hash=GENESIS_HASH))
        db.flush()


def record(
    db: Session,
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    cluster_id: int | None = None,
    severity: str = "info",
    actor_id: int | None = None,
    actor_role: str | None = None,
) -> AuditLog:
    ctx = context.current()
    # Locking the head row serializes writers, so sequence numbers have no gaps.
    head = db.execute(select(AuditChainHead).where(AuditChainHead.id == HEAD_ID).with_for_update()).scalar_one()
    row = AuditLog(
        seq=head.last_seq + 1,
        actor_id=actor_id if actor_id is not None else ctx.actor_id,
        actor_role=actor_role if actor_role is not None else ctx.actor_role,
        cluster_id=cluster_id,
        action=action,
        severity=severity,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        before=jsonable(before) if before is not None else None,
        after=jsonable(after) if after is not None else None,
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:400] or None,
        request_id=ctx.request_id,
        created_at=clock.now(),
        prev_hash=head.last_hash,
    )
    row.hash = compute_hash(row)
    db.add(row)
    head.last_seq = row.seq
    head.last_hash = row.hash
    db.flush()
    return row


def record_denial(
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: Any = None,
    reason: str = "",
    request_db: Session | None = None,
) -> None:
    """Audit a permission denial in its own transaction (FR-L2).

    The request's own session is rolled back first: the request is failing,
    and it must not hold the chain head lock while this entry is written.
    """
    if request_db is not None:
        request_db.rollback()
    with session_factory()() as db:
        record(
            db,
            "permission.denied",
            entity_type=entity_type,
            entity_id=entity_id,
            after={"attempted": action, "reason": reason} if reason else {"attempted": action},
            severity="warning",
        )
        db.commit()


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    broken_at_seq: int | None = None
    detail: str | None = None


def verify_chain(db: Session, batch_size: int = 1000) -> VerifyResult:
    """Recompute every hash from the start (FR-L4)."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    last_seq = 0
    while True:
        rows = (
            db.execute(select(AuditLog).where(AuditLog.seq > last_seq).order_by(AuditLog.seq).limit(batch_size))
            .scalars()
            .all()
        )
        if not rows:
            break
        for row in rows:
            if row.seq != expected_seq:
                return VerifyResult(False, checked, expected_seq, f"missing entry {expected_seq}")
            if row.prev_hash != expected_prev:
                return VerifyResult(False, checked, row.seq, "previous hash does not match")
            if compute_hash(row) != row.hash:
                return VerifyResult(False, checked, row.seq, "entry content does not match its hash")
            expected_prev = row.hash
            expected_seq += 1
            checked += 1
            last_seq = row.seq
        db.expunge_all()
    head = db.get(AuditChainHead, HEAD_ID)
    if head is not None and head.last_seq != checked:
        return VerifyResult(False, checked, checked + 1, "entries missing at the end of the chain")
    return VerifyResult(True, checked)


def run_verification(db: Session) -> VerifyResult:
    """Verify, store the outcome, and alert every admin if the chain is broken."""
    from app.mail import queue as mail_queue

    result = verify_chain(db)
    db.add(
        AuditVerification(
            ok=result.ok,
            checked_count=result.checked,
            broken_at_seq=result.broken_at_seq,
            detail=result.detail,
        )
    )
    if not result.ok:
        record(
            db,
            "audit.chain_broken",
            entity_type="audit_log",
            entity_id=result.broken_at_seq,
            after={"detail": result.detail},
            severity="critical",
        )
        mail_queue.alert_admins(db, "audit_chain_broken", {"seq": result.broken_at_seq, "detail": result.detail})
    db.commit()
    return result


def latest_verification(db: Session) -> AuditVerification | None:
    return db.execute(select(AuditVerification).order_by(AuditVerification.id.desc()).limit(1)).scalar_one_or_none()
