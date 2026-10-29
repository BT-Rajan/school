"""Changes become live events only once their transaction commits (FR-RT1).

Services already audit every state change, so the audit log is the source: each
entry for a live entity adds a pending event to its database session, and the
session's commit hands them to the broadcaster. A rollback drops them, so no
screen ever hears about a change that did not happen. Notifications add an event
for their one recipient.

Events carry only what changed (entity and id), never content. Each screen then
refetches through the API, which applies its own access rules again.
"""

from sqlalchemy import event
from sqlalchemy.orm import Session

# Entities whose changes appear on open screens.
LIVE = {
    "assignment",
    "cluster",
    "document",
    "evaluation",
    "form",
    "request",
    "school",
    "supervisor",
    "teacher",
    "user",
}

_KEY = "realtime_pending"


def emit(db: Session, entity: str, entity_id: object, *, user_id: int | None = None) -> None:
    """Queue an event on this transaction. user_id targets one person (notifications)."""
    db.info.setdefault(_KEY, []).append(
        {"entity": entity, "id": None if entity_id is None else str(entity_id), "user_id": user_id}
    )


def from_audit(db: Session, action: str, entity_type: str | None, entity_id: object) -> None:
    if entity_type in LIVE and action != "permission.denied" and entity_id is not None:
        emit(db, entity_type, entity_id)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    pending = session.info.pop(_KEY, None)
    if pending:
        from .broadcaster import broadcaster

        # De-duplicate: one save can write several audit rows about one record.
        unique = list({(e["entity"], e["id"], e["user_id"]): e for e in pending}.values())
        broadcaster.publish(unique)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)
