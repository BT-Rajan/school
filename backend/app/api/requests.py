from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.requests import access, service
from app.requests.service import ConfirmIn, CreateIn, ReasonIn, ReturnIn, SaveIn, SettingsIn

router = APIRouter(prefix="/api", tags=["requests"])


def _full(db: Session, principal: Principal, r) -> dict:
    return service.request_out(db, principal, r, full=True)


@router.get("/requests")
def list_requests(
    show: service.Filter | None = None,
    school_id: int | None = None,
    kind: str | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    return service.list_requests(
        db, principal, show=show, school_id=school_id, kind=kind, page=page, page_size=page_size
    )


@router.post("/requests", status_code=201)
def create(body: CreateIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return [service.request_out(db, principal, r) for r in service.create_standalone(db, principal, body)]


@router.get("/requests/{request_id}")
def get_request(request_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _full(db, principal, access.get_visible(db, principal, request_id))


@router.patch("/requests/{request_id}")
def save(
    request_id: int, body: SaveIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _full(db, principal, service.save(db, principal, request_id, body))


@router.post("/requests/{request_id}/submit")
def submit(
    request_id: int, body: SaveIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _full(db, principal, service.submit(db, principal, request_id, body))


@router.post("/requests/{request_id}/return")
def return_request(
    request_id: int, body: ReturnIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _full(db, principal, service.return_(db, principal, request_id, body))


@router.post("/requests/{request_id}/settings")
def update_settings(
    request_id: int, body: SettingsIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _full(db, principal, service.update_settings(db, principal, request_id, body))


@router.post("/requests/{request_id}/waive")
def waive(
    request_id: int, body: ReasonIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _full(db, principal, service.waive(db, principal, request_id, body))


@router.post("/requests/{request_id}/cancel")
def cancel(
    request_id: int, body: ReasonIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _full(db, principal, service.cancel(db, principal, request_id, body))


@router.post("/requests/{request_id}/confirm-move")
def confirm_move(
    request_id: int, body: ConfirmIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _full(db, principal, service.confirm_move(db, principal, request_id, body))


@router.get("/requests/{request_id}/history")
def history(request_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.history(db, principal, request_id)


class StandaloneIn(BaseModel):
    allowed: bool


@router.post("/catalog/reports/{report_id}/standalone")
def set_standalone(
    report_id: int, body: StandaloneIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    report = service.set_standalone_allowed(db, principal, report_id, body.allowed)
    return {"id": report.id, "standalone_allowed": report.standalone_allowed}
