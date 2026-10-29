from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.district import get_district
from app.errors import invalid
from app.files import service

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("", status_code=201)
async def upload(
    file: UploadFile = File(...), principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    limit = int(get_district(db).setting("upload_max_mb")) * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise invalid("file_too_large", {"max_mb": limit // (1024 * 1024)})
    return service.file_out(service.upload(db, principal, file.filename or "upload", content))


@router.get("")
def my_uploads(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.list_my_uploads(db, principal)


@router.get("/{file_id}")
def get_file(file_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.file_out(service.get_file(db, principal, file_id))


class LinkIn(BaseModel):
    disposition: Literal["inline", "attachment"] = "attachment"


@router.post("/{file_id}/link")
def create_link(
    file_id: int, body: LinkIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    link = service.create_link(db, principal, file_id, body.disposition)
    return {"url": link.url, "expires_at": link.expires_at}


@router.get("/download/{token}")
def download(token: str, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    file, disposition = service.resolve_link(db, principal, token)
    content = service.served_content(db, principal, file)
    extension = file.original_name.rsplit(".", 1)[-1]
    headers = {
        # An ASCII fallback name, plus the real (possibly Arabic) name in UTF-8.
        "Content-Disposition": (
            f"{disposition}; filename=\"file.{extension}\"; filename*=UTF-8''{quote(file.original_name)}"
        ),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if disposition == "inline":
        # Previews never run scripts (FR-FS4). Images get a full sandbox; a sandbox would stop
        # the browser's PDF viewer, so PDFs, already stripped of scripts at upload, get no-script rules.
        headers["Content-Security-Policy"] = (
            "default-src 'none'; object-src 'self'; frame-ancestors 'self'"
            if file.mime_type == "application/pdf"
            else "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"
        )
    return Response(content, media_type=file.mime_type, headers=headers)
