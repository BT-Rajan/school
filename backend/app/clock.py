"""Single source of the current time, so tests can move it."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

_frozen: datetime | None = None


def now() -> datetime:
    """Current time as naive UTC, matching how timestamps are stored."""
    if _frozen is not None:
        return _frozen
    return datetime.now(UTC).replace(tzinfo=None)


def freeze(at: datetime | None) -> None:
    global _frozen
    _frozen = at


def local_date(time_zone: str, at: datetime | None = None) -> date:
    """The calendar date in the district's time zone for a naive UTC time."""
    at = at or now()
    return at.replace(tzinfo=UTC).astimezone(ZoneInfo(time_zone)).date()
