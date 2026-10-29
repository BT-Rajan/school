"""Resumable uploads (FR-D6): start, send pieces, resume after a drop, complete.

Completing runs the normal upload pipeline (type check, cleaning, virus scan queue,
encryption), so a resumable upload is exactly as safe as a direct one.
"""

from datetime import timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.auth.deps import Principal
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.models import StoredFile, UploadSession
from app.security import crypto

from . import service as files
from . import storage

CHUNK_MAX = 4 * 1024 * 1024
ABANDONED_AFTER = timedelta(hours=48)


class StartIn(BaseModel):
    client_key: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)


def _context(u: UploadSession, index: int) -> str:
    return f"upload:{u.id}:{index}"


def upload_out(u: UploadSession) -> dict:
    return {"id": u.id, "received": u.received, "size": u.size, "file_id": u.file_id}


def start(db: Session, principal: Principal, body: StartIn) -> UploadSession:
    existing = db.execute(
        select(UploadSession).where(
            UploadSession.user_id == principal.user.id, UploadSession.client_key == body.client_key
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    limit = int(get_district(db).setting("upload_max_mb")) * 1024 * 1024
    if body.size > limit:
        raise invalid("file_too_large", {"max_mb": limit // (1024 * 1024)})
    u = UploadSession(
        user_id=principal.user.id,
        client_key=body.client_key,
        name=body.name,
        size=body.size,
        wrapped_key="",
    )
    db.add(u)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return start(db, principal, body)
    u.wrapped_key = crypto.wrap_key(crypto.new_data_key(), context=f"upload:{u.id}")
    db.commit()
    return u


def _own(db: Session, principal: Principal, upload_id: int, *, lock: bool = False) -> UploadSession:
    query = select(UploadSession).where(UploadSession.id == upload_id)
    if lock:
        query = query.with_for_update()
    u = db.execute(query).scalar_one_or_none()
    if u is None or u.user_id != principal.user.id:
        raise not_found()
    return u


def get(db: Session, principal: Principal, upload_id: int) -> UploadSession:
    return _own(db, principal, upload_id)


def put_chunk(db: Session, principal: Principal, upload_id: int, offset: int, data: bytes) -> UploadSession:
    """Pieces arrive in order. A piece already received is acknowledged, not stored twice."""
    u = _own(db, principal, upload_id, lock=True)
    if u.file_id is not None:
        return u
    if not data or len(data) > CHUNK_MAX:
        raise invalid("chunk_size_invalid", {"max_bytes": CHUNK_MAX})
    if offset + len(data) <= u.received:
        return u  # a retry of a piece we have
    if offset != u.received:
        raise AppError(409, "upload_offset_mismatch", {"received": u.received})
    if u.received + len(data) > u.size:
        raise invalid("upload_too_long")
    key = crypto.unwrap_key(u.wrapped_key, context=f"upload:{u.id}")
    object_key = storage.new_key()
    storage.get_store().put(object_key, crypto.seal(data, key, context=_context(u, len(u.chunks))))
    u.chunks = [*u.chunks, object_key]
    u.received += len(data)
    db.commit()
    return u


def complete(db: Session, principal: Principal, upload_id: int) -> StoredFile:
    u = _own(db, principal, upload_id, lock=True)
    if u.file_id is not None:
        return db.get(StoredFile, u.file_id)
    if u.received != u.size:
        raise AppError(409, "upload_incomplete", {"received": u.received, "size": u.size})
    key = crypto.unwrap_key(u.wrapped_key, context=f"upload:{u.id}")
    store = storage.get_store()
    content = b"".join(crypto.open_sealed(store.get(k), key, context=_context(u, i)) for i, k in enumerate(u.chunks))
    pieces = list(u.chunks)
    upload_id = u.id
    file = files.upload(db, principal, u.name, content)  # commits
    u = db.get(UploadSession, upload_id)
    u.file_id, u.completed_at, u.chunks = file.id, clock.now(), []
    db.commit()
    for k in pieces:
        store.delete(k)
    return file


def prune(db: Session) -> int:
    """Housekeeping: drop pieces of uploads abandoned for two days."""
    stale = db.execute(
        select(UploadSession).where(
            UploadSession.file_id.is_(None), UploadSession.created_at < clock.now() - ABANDONED_AFTER
        )
    ).scalars()
    store = storage.get_store()
    count = 0
    for u in list(stale):
        for k in u.chunks:
            store.delete(k)
        db.delete(u)
        count += 1
    db.commit()
    return count
