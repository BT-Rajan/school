from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class AuditLog(Base):
    """Tamper-evident audit trail (FR-L1).

    The application database user has INSERT and SELECT only on this table
    (FR-L3). Each row's hash covers its content and the previous row's hash.
    """

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    actor_id: Mapped[int | None] = mapped_column(index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    cluster_id: Mapped[int | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AuditChainHead(Base):
    """Single row holding the latest sequence and hash.

    Writers lock this row, which serializes audit inserts. Verification never
    trusts it: the chain is recomputed from audit_log itself.
    """

    __tablename__ = "audit_chain_head"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_hash: Mapped[str] = mapped_column(String(64))


class AuditVerification(Base):
    __tablename__ = "audit_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(default=clock.now)
    ok: Mapped[bool]
    checked_count: Mapped[int]
    broken_at_seq: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[str | None] = mapped_column(String(500))
