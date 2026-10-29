"""Upload, scan and serve files (FR-FS1 to FR-FS4).

Upload: check limits, detect the type from content, sanitize, encrypt with a
new per-file key, store, and queue a virus scan. Nothing is served until the
scan says it is clean.

Download: the owning feature's access rule is checked, then a link is issued
that lasts 5 minutes and works only in the session that asked for it. The
access rule is checked again when the link is used.
"""

import base64
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.auth import rate_limit
from app.auth.deps import Principal
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.mail import queue as mail
from app.models import MailPriority, User
from app.models.files import StoredFile
from app.security import crypto, tokens

from . import inspect
from .scanner import ScannerUnavailable, get_scanner
from .storage import get_store, new_key

log = logging.getLogger(__name__)

LINK_SECONDS = 300
MAX_SCAN_ATTEMPTS = 10

# Access rules by owner type. Each feature that owns files registers its rule.
AccessRule = Callable[[Session, Principal, StoredFile], bool]
# Optional change to content as it is served, such as a viewer watermark (FR-D27).
ServeTransform = Callable[[Session, Principal, StoredFile, bytes], bytes]
_ACCESS: dict[str, AccessRule] = {
    # A fresh upload is visible only to the person who uploaded it.
    "upload": lambda _db, principal, f: f.uploaded_by == principal.user.id,
}
_TRANSFORMS: dict[str, ServeTransform] = {}
# Owners whose files are opened only through the owner's own link, which records the view.
_OWNER_LINKS_ONLY: set[str] = set()


def register_owner(
    owner_type: str, rule: AccessRule, transform: ServeTransform | None = None, *, owner_links_only: bool = False
) -> None:
    _ACCESS[owner_type] = rule
    if transform is not None:
        _TRANSFORMS[owner_type] = transform
    if owner_links_only:
        _OWNER_LINKS_ONLY.add(owner_type)


def served_content(db: Session, principal: Principal, file: StoredFile) -> bytes:
    content = read_content(file)
    transform = _TRANSFORMS.get(file.owner_type)
    return transform(db, principal, file, content) if transform else content


def _context(file: StoredFile) -> str:
    return f"file:{file.storage_key}"


def file_out(file: StoredFile) -> dict:
    return {
        "id": file.id,
        "name": file.original_name,
        "mime_type": file.mime_type,
        "size": file.size,
        "pages": file.page_count,
        "sha256": file.sha256,
        "status": file.scan_status,
        "created_at": file.created_at,
    }


# Upload ------------------------------------------------------------------------


def upload(db: Session, principal: Principal, filename: str, content: bytes) -> StoredFile:
    district = get_district(db)
    max_bytes = int(district.setting("upload_max_mb")) * 1024 * 1024
    if len(content) > max_bytes:
        raise invalid("file_too_large", {"max_mb": district.setting("upload_max_mb")})
    if not content:
        raise invalid("file_empty")
    rate_limit.require(
        db, f"upload:user:{principal.user.id}", int(district.setting("upload_rate_per_hour")), timedelta(hours=1)
    )
    cleaned = inspect.clean(filename, content, int(district.setting("upload_max_pages")))

    quota = int(district.setting("storage_quota_mb_per_user")) * 1024 * 1024
    used = db.execute(
        select(func.coalesce(func.sum(StoredFile.size), 0)).where(
            StoredFile.uploaded_by == principal.user.id, StoredFile.deleted_at.is_(None)
        )
    ).scalar_one()
    if used + len(cleaned.content) > quota:
        raise AppError(409, "storage_quota_exceeded", {"quota_mb": district.setting("storage_quota_mb_per_user")})

    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0][:200] or "file"
    file = store(
        db, principal.user.id, f"{base}{cleaned.extension}", cleaned.content, cleaned.mime_type, cleaned.page_count
    )
    db.commit()
    return file


def store(
    db: Session,
    uploaded_by: int,
    name: str,
    content: bytes,
    mime_type: str,
    page_count: int | None,
    *,
    owner_type: str = "upload",
    owner_id: int | None = None,
) -> StoredFile:
    """Encrypt content with a new key, write it, record it, and queue its virus scan. The caller commits."""
    file = StoredFile(
        storage_key=new_key(),
        owner_type=owner_type,
        owner_id=owner_id,
        uploaded_by=uploaded_by,
        original_name=name[:255],
        mime_type=mime_type,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        page_count=page_count,
        scan_status="pending",
        scan_after=clock.now(),
        created_at=clock.now(),
        wrapped_key="",
    )
    data_key = crypto.new_data_key()
    file.wrapped_key = crypto.wrap_key(data_key, context=_context(file))
    get_store().put(file.storage_key, crypto.seal(content, data_key, context=_context(file)))
    db.add(file)
    db.flush()
    audit.record(
        db,
        "file.uploaded",
        entity_type="file",
        entity_id=file.id,
        after={"sha256": file.sha256, "size": file.size, "mime_type": file.mime_type, "pages": file.page_count},
        actor_id=uploaded_by,
    )
    return file


def read_content(file: StoredFile) -> bytes:
    data_key = crypto.unwrap_key(file.wrapped_key, context=_context(file))
    content = crypto.open_sealed(get_store().get(file.storage_key), data_key, context=_context(file))
    if hashlib.sha256(content).hexdigest() != file.sha256:
        raise AppError(500, "file_integrity_failed")
    return content


# Scanning ------------------------------------------------------------------------


def scan_pending(db: Session, limit: int = 20) -> int:
    """Scan files waiting for a verdict. Called by the worker."""
    files = (
        db.execute(
            select(StoredFile)
            .where(StoredFile.scan_status == "pending", StoredFile.scan_after <= clock.now())
            .order_by(StoredFile.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    scanner = get_scanner()
    done = 0
    for file in files:
        file.scan_attempts += 1
        try:
            result = scanner.scan(read_content(file))
        except ScannerUnavailable as exc:
            # Stays pending, so it is never served; retried with backoff.
            log.warning("scanner unavailable for file %s: %s", file.id, exc)
            file.scan_detail = "scanner unavailable"
            file.scan_after = clock.now() + timedelta(minutes=min(60, 2**file.scan_attempts))
            if file.scan_attempts == MAX_SCAN_ATTEMPTS:
                mail.alert_admins(db, "scanner_unavailable", {})
            continue
        file.scanned_at = clock.now()
        file.scan_detail = result.detail
        if result.clean:
            file.scan_status = "clean"
            audit.record(db, "file.scanned", entity_type="file", entity_id=file.id, after={"result": "clean"})
        else:
            file.scan_status = "quarantined"
            audit.record(
                db,
                "file.quarantined",
                entity_type="file",
                entity_id=file.id,
                after={"signature": result.detail},
                severity="warning",
                actor_id=None,
                actor_role="scanner",
            )
            uploader = db.get(User, file.uploaded_by)
            if uploader is not None:
                mail.send_to_user(
                    db, uploader, "file_quarantined", {"name": file.original_name}, MailPriority.INFORMATIONAL
                )
            mail.alert_admins(db, "file_quarantined_admin", {"id": file.id, "signature": result.detail})
        done += 1
    db.commit()
    return done


# Access and download --------------------------------------------------------------


def get_file(db: Session, principal: Principal, file_id: int) -> StoredFile:
    file = db.get(StoredFile, file_id)
    rule = _ACCESS.get(file.owner_type) if file else None
    if file is None or file.deleted_at is not None or rule is None or not rule(db, principal, file):
        audit.record_denial("file.access", entity_type="file", entity_id=file_id, reason="scope", request_db=db)
        raise not_found()
    return file


def _sign(payload: str) -> str:
    return tokens.keyed_hash("file-link", payload)


@dataclass
class Link:
    url: str
    expires_at: object


def create_link(
    db: Session, principal: Principal, file_id: int, disposition: str = "attachment", *, via_owner: bool = False
) -> Link:
    file = get_file(db, principal, file_id)
    if file.owner_type in _OWNER_LINKS_ONLY and not via_owner:
        # Scanned reports open through /api/documents/{id}/link, so the owner sees who opened them (FR-L9).
        raise not_found()
    if file.scan_status == "pending":
        raise AppError(409, "file_not_ready")
    if file.scan_status != "clean":
        raise AppError(409, "file_quarantined")
    expires = int(time.time()) + LINK_SECONDS
    payload = f"{file.id}.{principal.session.id}.{expires}.{'inline' if disposition == 'inline' else 'attachment'}"
    token = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + _sign(payload)
    audit.record(db, "file.link_created", entity_type="file", entity_id=file.id, after={"disposition": disposition})
    db.commit()
    return Link(f"/api/files/download/{token}", clock.now() + timedelta(seconds=LINK_SECONDS))


def resolve_link(db: Session, principal: Principal, token: str) -> tuple[StoredFile, str]:
    try:
        encoded, signature = token.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        file_id, session_id, expires, disposition = payload.split(".")
    except (ValueError, UnicodeDecodeError) as exc:
        raise not_found() from exc
    if not tokens.constant_time_equal(signature, _sign(payload)):
        raise not_found()
    if int(expires) < time.time():
        raise AppError(410, "link_expired")
    if int(session_id) != principal.session.id:
        # A link passed to someone else, or used after signing out, does not work.
        audit.record_denial("file.download", entity_type="file", entity_id=file_id, reason="session", request_db=db)
        raise not_found()
    file = get_file(db, principal, int(file_id))
    if file.scan_status != "clean":
        raise not_found()
    audit.record(db, "file.downloaded", entity_type="file", entity_id=file.id, after={"disposition": disposition})
    db.commit()
    return file, disposition


def list_my_uploads(db: Session, principal: Principal) -> list[dict]:
    files = db.execute(
        select(StoredFile)
        .where(
            StoredFile.uploaded_by == principal.user.id,
            StoredFile.owner_type == "upload",
            StoredFile.deleted_at.is_(None),
        )
        .order_by(StoredFile.id.desc())
        .limit(100)
    ).scalars()
    return [file_out(f) for f in files]
