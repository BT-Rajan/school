import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.audit import service as audit
from app.config import get_settings
from app.models import AuditLog, AuditVerification, Role

from .helpers import deliver_mail, make_user


def _write(db, n: int) -> None:
    for i in range(n):
        audit.record(db, "test.event", entity_type="thing", entity_id=i, after={"n": i, "name": "مدرسة"})
    db.commit()


def test_chain_verifies(db):
    _write(db, 5)
    result = audit.verify_chain(db)
    assert result.ok and result.checked == 5
    rows = db.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().all()
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0].prev_hash == audit.GENESIS_HASH
    assert all(b.prev_hash == a.hash for a, b in zip(rows, rows[1:], strict=False))


def test_tampered_content_is_detected(db, root_engine, outbox):
    make_user(Role.DISTRICT_ADMIN, "admin1@example.org")
    _write(db, 4)
    with root_engine.begin() as conn:
        conn.execute(text("UPDATE audit_log SET after = JSON_OBJECT('n', 99) WHERE seq = 3"))
    result = audit.run_verification(db)
    assert not result.ok
    assert result.broken_at_seq == 3
    stored = db.execute(select(AuditVerification)).scalar_one()
    assert stored.ok is False
    # A critical entry is written and every admin is alerted (FR-L4).
    critical = db.execute(select(AuditLog).where(AuditLog.action == "audit.chain_broken")).scalar_one()
    assert critical.severity == "critical"
    deliver_mail()
    assert any("integrity" in m.subject for m in outbox if m.to == "admin1@example.org")


def test_deleted_entry_is_detected(db, root_engine):
    _write(db, 4)
    with root_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE seq = 2"))
    result = audit.verify_chain(db)
    assert not result.ok and result.broken_at_seq == 2


def test_truncated_tail_is_detected(db, root_engine):
    _write(db, 4)
    with root_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE seq = 4"))
    result = audit.verify_chain(db)
    assert not result.ok


def test_app_database_user_cannot_change_audit_rows(db):
    """FR-L3: INSERT and SELECT only."""
    _write(db, 1)
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one() == 1
        with pytest.raises((OperationalError, ProgrammingError)):
            conn.execute(text("UPDATE audit_log SET action = 'x' WHERE seq = 1"))
        with pytest.raises((OperationalError, ProgrammingError)):
            conn.execute(text("DELETE FROM audit_log WHERE seq = 1"))
    engine.dispose()


def test_changed_fields_keeps_only_differences():
    before, after = audit.changed_fields({"a": 1, "b": 2}, {"a": 1, "b": 3})
    assert before == {"b": 2} and after == {"b": 3}
