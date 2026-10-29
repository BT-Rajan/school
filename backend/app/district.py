from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import District


def get_district(db: Session) -> District:
    district = db.execute(select(District).limit(1)).scalar_one_or_none()
    if district is None:
        raise AppError(503, "district_not_configured")
    return district


def local_midnight_utc(district: District, day: date) -> datetime:
    """Naive UTC instant of 00:00 on a district-local date."""
    local = datetime.combine(day, time.min, tzinfo=ZoneInfo(district.time_zone))
    return local.astimezone(UTC).replace(tzinfo=None)


def local_time_utc(district: District, day: date, hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    local = datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(district.time_zone))
    return local.astimezone(UTC).replace(tzinfo=None)
