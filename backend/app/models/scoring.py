from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class ScoreRuleSet(Base):
    """A versioned scoring formula for one form version (FR-SC2).

    Drafts can change; an active rule set is fixed, so every score it gave can be worked
    out again. At most one is active per form version; activating another retires it.
    """

    __tablename__ = "score_rule_sets"
    __table_args__ = (Index("ix_score_rule_sets_form_status", "form_version_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_versions.id"))
    number: Mapped[int]  # 1, 2, ... within the form version
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft, active, retired, discarded
    rules: Mapped[dict[str, Any]] = mapped_column(default=dict)
    note: Mapped[str | None] = mapped_column(String(1000))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}


class ScoreRecalculation(Base):
    """A recorded recalculation (FR-SC3): stored scores change only through one of these."""

    __tablename__ = "score_recalculations"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_versions.id"), index=True)
    rule_set_id: Mapped[int] = mapped_column(ForeignKey("score_rule_sets.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued, running, done, failed
    evaluations: Mapped[int] = mapped_column(default=0)
    changed: Mapped[int] = mapped_column(default=0)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(default=clock.now)
    finished_at: Mapped[datetime | None]
