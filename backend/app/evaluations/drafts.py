"""Draft evaluations affected by assignment changes (FR-AS2, FR-AS3, FR-AS9).

Only the evaluation drafts move. Scanned documents never move between supervisors.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.models import Evaluation, EvaluationSection, School, Supervisor
from app.notifications import service as notify


def open_draft_ids(db: Session, supervisor_id: int, school_id: int) -> list[int]:
    return list(
        db.execute(
            select(Evaluation.id).where(
                Evaluation.supervisor_id == supervisor_id,
                Evaluation.school_id == school_id,
                Evaluation.status == "draft",
            )
        ).scalars()
    )


def transfer(db: Session, draft_ids: list[int], to_supervisor_id: int) -> None:
    target = db.get(Supervisor, to_supervisor_id)
    moved = list(db.execute(select(Evaluation).where(Evaluation.id.in_(draft_ids)).with_for_update()).scalars())
    for e in moved:
        before = e.supervisor_id
        e.supervisor_id = target.id
        db.execute(
            update(EvaluationSection)
            .where(EvaluationSection.evaluation_id == e.id, EvaluationSection.respondent == "supervisor")
            .values(respondent_user_id=target.user_id)
        )
        audit.record(
            db,
            "evaluation.transferred",
            entity_type="evaluation",
            entity_id=e.id,
            before={"supervisor_id": before},
            after={"supervisor_id": target.id},
        )
    if moved:
        school = db.get(School, moved[0].school_id)
        notify.notify(
            db,
            target.user_id,
            "evaluations_transferred",
            {"count": len(moved), "school": school.name, "school_code": school.code},
        )


def cancel(db: Session, draft_ids: list[int], reason: str) -> None:
    for e in db.execute(select(Evaluation).where(Evaluation.id.in_(draft_ids)).with_for_update()).scalars():
        e.status, e.cancelled_at, e.cancel_reason = "cancelled", clock.now(), reason
        audit.record(
            db,
            "evaluation.cancelled",
            entity_type="evaluation",
            entity_id=e.id,
            after={"reason": reason, "by_assignment_change": True},
        )
