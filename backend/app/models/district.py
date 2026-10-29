from datetime import datetime
from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled_locales": ["en", "ar"],
    "session_idle_hours": 12,
    "totp_required_roles": ["district_admin", "form_author"],
    "mail_daily_limit": 500,
    "mail_reserve_fraction": 0.4,
    "invitation_daily_cap": 150,
    "digest_time": "18:00",
    "audit_verify_time": "02:00",
    "audit_retention_years": 7,
    "custom_field_limit": 15,
    "upload_max_mb": 25,
    "upload_max_pages": 50,
    "upload_rate_per_hour": 60,
    "storage_quota_mb_per_user": 2048,
}


class District(Base):
    """The single district this deployment serves."""

    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name_en: Mapped[str] = mapped_column(String(200))
    name_ar: Mapped[str] = mapped_column(String(200))
    default_locale: Mapped[str] = mapped_column(String(8), default="en")
    time_zone: Mapped[str] = mapped_column(String(64))
    date_format: Mapped[str] = mapped_column(String(16), default="D/MM/YYYY")
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}

    def setting(self, key: str) -> Any:
        return (self.settings or {}).get(key, DEFAULT_SETTINGS[key])
