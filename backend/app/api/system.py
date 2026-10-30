import re
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.deps import Principal, admin_only
from app.config import get_settings
from app.db import get_db
from app.district import get_district
from app.errors import conflict, invalid, not_found
from app.files import service as files
from app.mail import queue as mail
from app.mail.templates import NOTICES
from app.models import Role, StoredFile
from app.notifications.service import CHANNELS

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
        "logo": district.setting("logo_file_id") is not None,
    }


def _bounded(low: int, high: int) -> Callable[[Any], int]:
    def cast(value: Any) -> int:
        number = int(value)
        if not low <= number <= high:
            raise ValueError("out of range")
        return number

    return cast


def _hhmm(value: Any) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value)):
        raise ValueError("not a time")
    return str(value)


def _locales(value: Any) -> list[str]:
    # English is the default language; Arabic can be turned off but English cannot (FR-I2).
    chosen = [x for x in ("en", "ar") if x in list(value)]
    if "en" not in chosen or set(value) - set(chosen):
        raise ValueError("unknown locale")
    return chosen


def _totp_roles(value: Any) -> list[str]:
    roles = {r.value for r in Role}
    chosen = sorted(set(value))
    # Admins hold the keys to everything else, so their authenticator stays required (FR-A3).
    if set(chosen) - roles or Role.DISTRICT_ADMIN.value not in chosen:
        raise ValueError("bad roles")
    return chosen


def _sender(value: Any) -> str:
    text_value = str(value).strip()
    if len(text_value) > 100 or any(c in text_value for c in "\r\n<>"):
        raise ValueError("bad sender")
    return text_value


def _notice_defaults(value: Any) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for type_, channels in dict(value).items():
        if type_ not in NOTICES or not isinstance(channels, dict) or set(channels) - set(CHANNELS):
            raise ValueError("unknown notice")
        out[type_] = {c: bool(v) for c, v in channels.items()}
    return out


EDITABLE_SETTINGS: dict[str, Callable[[Any], Any]] = {
    "enabled_locales": _locales,
    "session_idle_hours": _bounded(1, 24),
    "totp_required_roles": _totp_roles,
    "mail_daily_limit": _bounded(10, 1_000_000),
    "mail_reserve_fraction": float,
    "mail_sender_name": _sender,
    "invitation_daily_cap": _bounded(1, 100_000),
    "digest_time": _hhmm,
    "audit_verify_time": _hhmm,
    # FR-L8: seven years by default; the district sets it within its legal limits.
    "audit_retention_years": _bounded(1, 50),
    "custom_field_limit": _bounded(0, 15),
    "upload_max_mb": int,
    "upload_max_pages": _bounded(1, 500),
    "upload_rate_per_hour": _bounded(1, 10_000),
    "storage_quota_mb_per_user": _bounded(10, 1_000_000),
    "document_retention_years": _bounded(1, 50),
    "acknowledge_overdue_days": _bounded(1, 90),
    "notification_defaults": _notice_defaults,
}


class DistrictUpdate(BaseModel):
    version: int
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, min_length=1, max_length=200)
    default_locale: str | None = Field(default=None, pattern="^(en|ar)$")
    time_zone: str | None = Field(default=None, max_length=64)
    settings: dict[str, Any] | None = None


@router.get("/admin/settings")
def admin_settings(_: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    district = get_district(db)
    return {
        "code": district.code,
        "name_en": district.name_en,
        "name_ar": district.name_ar,
        "default_locale": district.default_locale,
        "time_zone": district.time_zone,
        "date_format": district.date_format,
        "settings": {key: district.setting(key) for key in EDITABLE_SETTINGS},
        "logo": district.setting("logo_file_id") is not None,
        # Set on the server with its credentials (deployment guide), shown here for reference.
        "mail_provider": get_settings().mail_provider,
        "mail_sender": get_settings().mail_sender,
        "notice_types": list(NOTICES),
        "version": district.version,
    }


@router.patch("/admin/settings")
def update_settings(body: DistrictUpdate, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    district = get_district(db)
    if body.version != district.version:
        raise conflict({"version": district.version})
    fields = ("code", "name_en", "name_ar", "default_locale", "time_zone")
    before = {**{f: getattr(district, f) for f in fields}, **(district.settings or {})}
    if body.time_zone:
        try:
            ZoneInfo(body.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise invalid("setting_invalid", {"key": "time_zone"}) from exc
    for f in fields:
        if getattr(body, f):
            setattr(district, f, getattr(body, f))
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
    if district.default_locale not in district.setting("enabled_locales"):
        raise invalid("setting_invalid", {"key": "default_locale"})
    after = {**{f: getattr(district, f) for f in fields}, **(district.settings or {})}
    old, new = audit.changed_fields(before, after)
    db.flush()
    if new:
        audit.record(db, "settings.updated", entity_type="district", entity_id=district.id, before=old, after=new)
    db.commit()
    return admin_settings(_, db)


# The district's logo (FR-AD1), shown on every screen including sign-in, so anyone may fetch it.
files.register_owner("district_logo", lambda _db, _principal, _file: True)
LOGO_TYPES = ("image/png", "image/jpeg")


@router.put("/admin/logo")
async def upload_logo(
    file: UploadFile = File(...), principal: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    stored = files.upload(db, principal, file.filename or "logo", await file.read())
    if stored.mime_type not in LOGO_TYPES:
        raise invalid("logo_type")
    district = get_district(db)
    stored.owner_type, stored.owner_id = "district_logo", district.id
    previous = district.setting("logo_file_id")
    district.settings = {**(district.settings or {}), "logo_file_id": stored.id}
    db.flush()
    audit.record(
        db,
        "settings.logo_changed",
        entity_type="district",
        entity_id=district.id,
        after={"file_id": stored.id, "previous": previous},
    )
    db.commit()
    return admin_settings(principal, db)


@router.get("/district/logo")
def logo(db: Session = Depends(get_db)):
    file_id = get_district(db).setting("logo_file_id")
    file = db.get(StoredFile, file_id) if file_id else None
    if file is None or file.scan_status != "clean":
        raise not_found()
    return Response(
        files.read_content(file),
        media_type=file.mime_type,
        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


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
