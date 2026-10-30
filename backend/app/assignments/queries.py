"""Assignment lookups used across features. Depends only on models, so any module may import it."""

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import per_session
from app.models import Supervisor, SupervisorAssignment


def covering(day: date):
    """SQL condition: the assignment covers this day."""
    return (SupervisorAssignment.start_date <= day) & or_(
        SupervisorAssignment.end_date.is_(None), SupervisorAssignment.end_date >= day
    )


def not_ended(day: date):
    """SQL condition: the assignment is current or starts later."""
    return or_(SupervisorAssignment.end_date.is_(None), SupervisorAssignment.end_date >= day)


def open_count(db: Session, day: date, *, school_id: int | None = None, supervisor_id: int | None = None) -> int:
    query = select(func.count()).select_from(SupervisorAssignment).where(not_ended(day))
    if school_id is not None:
        query = query.where(SupervisorAssignment.school_id == school_id)
    if supervisor_id is not None:
        query = query.where(SupervisorAssignment.supervisor_id == supervisor_id)
    return db.execute(query).scalar_one()


def supervisor_for_user(db: Session, user_id: int) -> Supervisor | None:
    return per_session(
        db,
        f"supervisor:{user_id}",
        lambda: db.execute(select(Supervisor).where(Supervisor.user_id == user_id)).scalar_one_or_none(),
    )


def school_ids_for_supervisor(db: Session, supervisor_id: int, day: date | None = None) -> set[int]:
    """Schools the supervisor is assigned to on the day, or ever if no day is given."""
    query = select(SupervisorAssignment.school_id).where(SupervisorAssignment.supervisor_id == supervisor_id)
    if day is not None:
        query = query.where(covering(day))
    return set(db.execute(query).scalars())


def windows(db: Session, supervisor_id: int, school_id: int) -> list[SupervisorAssignment]:
    return list(
        db.execute(
            select(SupervisorAssignment)
            .where(SupervisorAssignment.supervisor_id == supervisor_id, SupervisorAssignment.school_id == school_id)
            .order_by(SupervisorAssignment.start_date)
        ).scalars()
    )


def date_in_window(db: Session, supervisor_id: int, school_id: int, day: date) -> bool:
    """FR-AS6 and FR-D5: the date falls inside one of the supervisor's windows for the school."""
    return any(a.covers(day) for a in windows(db, supervisor_id, school_id))
