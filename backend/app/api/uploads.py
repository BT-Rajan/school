from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.files import resumable
from app.files import service as files
from app.files.resumable import StartIn

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("", status_code=201)
def start(body: StartIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return resumable.upload_out(resumable.start(db, principal, body))


@router.get("/{upload_id}")
def status(upload_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return resumable.upload_out(resumable.get(db, principal, upload_id))


@router.put("/{upload_id}/chunks")
async def put_chunk(
    upload_id: int,
    request: Request,
    offset: int = Query(ge=0),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    data = await request.body()
    return resumable.upload_out(resumable.put_chunk(db, principal, upload_id, offset, data))


@router.post("/{upload_id}/complete")
def complete(upload_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return files.file_out(resumable.complete(db, principal, upload_id))
