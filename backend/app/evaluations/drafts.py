"""Draft evaluations affected by assignment changes (FR-AS2, FR-AS3, FR-AS9).

Filled in with the evaluations feature; until then there are no drafts.
"""

from sqlalchemy.orm import Session


def open_draft_ids(db: Session, supervisor_id: int, school_id: int) -> list[int]:
    return []


def transfer(db: Session, draft_ids: list[int], to_supervisor_id: int) -> None:
    return None


def cancel(db: Session, draft_ids: list[int], reason: str) -> None:
    return None
