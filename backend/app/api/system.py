from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.deps import Principal, admin_only
from app.config import get_settings
from app.db import get_db
from app.district import get_district
from app.errors import conflict, invalid
from app.mail import queue as mail

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/district")
def district_public(db: Session = Depends(get_db)):
    """What the sign-in page needs before anyone is signed in."""
    district = get_district(db)
    return {
        "code": district.code,
        "name_en": district.name_en,
        "name_ar": district.name_ar,
        "default_locale": district.default_locale,
        "enabled_locales": district.setting("enabled_locales"),
        "date_format": district.date_format,
        "time_zone": district.time_zone,
    }


EDITABLE_SETTINGS = {
    "session_idle_hours": int,
    "mail_daily_limit": int,
    "mail_reserve_fraction": float,
    "invitation_daily_cap": int,
    "digest_time": str,
    "custom_field_limit": int,
    "upload_max_mb": int,
    "upload_max_pages": int,
    "upload_rate_per_hour": int,
    "storage_quota_mb_per_user": int,
    "document_retention_years": int,
    "acknowledge_overdue_days": int,
}


class DistrictUpdate(BaseModel):
    version: int
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, min_length=1, max_length=200)
    settings: dict[str, Any] | None = None


@router.get("/admin/settings")
def admin_settings(_: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    district = get_district(db)
    return {
        "name_en": district.name_en,
        "name_ar": district.name_ar,
        "time_zone": district.time_zone,
        "date_format": district.date_format,
        "settings": {key: district.setting(key) for key in EDITABLE_SETTINGS},
        "version": district.version,
    }


@router.patch("/admin/settings")
def update_settings(body: DistrictUpdate, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    district = get_district(db)
    if body.version != district.version:
        raise conflict({"version": district.version})
    before = {"name_en": district.name_en, "name_ar": district.name_ar, **(district.settings or {})}
    if body.name_en:
        district.name_en = body.name_en
    if body.name_ar:
        district.name_ar = body.name_ar
    if body.settings:
        merged = dict(district.settings or {})
        for key, value in body.settings.items():
            caster = EDITABLE_SETTINGS.get(key)
            if caster is None:
                raise invalid("setting_unknown", {"key": key})
            try:
                merged[key] = caster(value)
            except (TypeError, ValueError) as exc:
                raise invalid("setting_invalid", {"key": key}) from exc
        if not 0 <= merged.get("mail_reserve_fraction", 0.4) < 1:
            raise invalid("setting_invalid", {"key": "mail_reserve_fraction"})
        # Uploads must fit under the server's request ceiling (SCES_MAX_UPLOAD_REQUEST_MB).
        if not 1 <= merged.get("upload_max_mb", 25) < get_settings().max_upload_request_mb:
            raise invalid("setting_invalid", {"key": "upload_max_mb"})
        district.settings = merged
    after = {"name_en": district.name_en, "name_ar": district.name_ar, **(district.settings or {})}
    old, new = audit.changed_fields(before, after)
    db.flush()
    if new:
        audit.record(db, "settings.updated", entity_type="district", entity_id=district.id, before=old, after=new)
    db.commit()
    return admin_settings(_, db)


@router.get("/admin/status")
def admin_status(_: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    """Audit chain state and mail budget for the admin dashboard."""
    latest = audit.latest_verification(db)
    return {
        "audit": (
            {
                "ok": latest.ok,
                "ran_at": latest.ran_at,
                "checked": latest.checked_count,
                "broken_at_seq": latest.broken_at_seq,
                "detail": latest.detail,
            }
            if latest
            else None
        ),
        "mail": mail.usage_today(db),
    }
