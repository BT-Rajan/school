from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class SupervisorAssignment(Base):
    """A supervisor's window of responsibility for a school (FR-AS1).

    end_date is inclusive; an open-ended assignment has none. Ending an
    assignment sets end_date and keeps the row, so history is never lost
    (FR-AS3, FR-AS5).
    """

    __tablename__ = "supervisor_assignments"
    __table_args__ = (Index("ix_supervisor_assignments_school_dates", "school_id", "start_date", "end_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    supervisor_id: Mapped[int] = mapped_column(ForeignKey("supervisors.id"), index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    reason: Mapped[str | None] = mapped_column(String(500))
    end_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ended_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    ended_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}

    def covers(self, day: date) -> bool:
        return self.start_date <= day and (self.end_date is None or day <= self.end_date)
