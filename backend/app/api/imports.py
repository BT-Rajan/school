from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.deps import Principal, structure_managers
from app.db import get_db
from app.errors import invalid
from app.structure import imports

router = APIRouter(prefix="/api", tags=["imports"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post("/imports/{entity}/preview")
async def preview(
    entity: str,
    file: UploadFile = File(...),
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise invalid("file_too_large", {"max_bytes": MAX_UPLOAD_BYTES})
    batch = imports.preview(db, principal, entity, file.filename or "upload", content)
    return imports.batch_out(db, batch)


@router.post("/imports/{batch_id}/commit")
def commit(batch_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return imports.batch_out(db, imports.commit(db, principal, batch_id))


@router.get("/imports/templates/{entity}")
def import_template(
    entity: str, locale: str = Query(default="en", pattern="^(en|ar)$"), _: Principal = Depends(structure_managers)
):
    return Response(
        imports.template(entity, locale),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{entity}-template.csv"'},
    )


@router.get("/exports/{entity}")
def export(
    entity: str,
    format: str = Query(default="xlsx", pattern="^(csv|xlsx)$"),
    locale: str = Query(default="en", pattern="^(en|ar)$"),
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    header, rows = imports.export_rows(db, principal, entity, locale)
    if format == "csv":
        body, media = imports.to_csv(header, rows), "text/csv; charset=utf-8"
    else:
        body = imports.to_xlsx(header, rows, rtl=locale == "ar")
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{entity}.{format}"'}
    )
