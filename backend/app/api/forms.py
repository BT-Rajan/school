from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.forms import service
from app.forms.service import CloseIn, CommentIn, FormUpdate, PublishIn, ReportIn, VersionIn, WindowIn

router = APIRouter(prefix="/api", tags=["forms"])


class VersionOnly(BaseModel):
    version: int


class ReturnIn(VersionOnly, CommentIn):
    pass


@router.get("/catalog")
def catalog(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.catalog(db, principal)


@router.post("/catalog/reports", status_code=201)
def create_report(body: ReportIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    report = service.create_report(db, principal, body)
    return {"id": report.id, "report_code": report.report_code, "subject_type": report.subject_type}


@router.post("/catalog/reports/{report_id}/versions", status_code=201)
def create_version(
    report_id: int, body: VersionIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.form_out(db, service.create_version(db, principal, report_id, body), with_problems=True)


@router.get("/forms")
def list_forms(
    status: str | None = None, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.list_forms(db, principal, status)


@router.get("/forms/{form_id}")
def get_form(form_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    form = service.get_form(db, principal, form_id)
    builder = principal.role.value in ("form_author", "district_admin")
    return service.form_out(db, form, with_problems=builder)


@router.patch("/forms/{form_id}")
def update_form(
    form_id: int, body: FormUpdate, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.form_out(db, service.update_form(db, principal, form_id, body), with_problems=True)


@router.post("/forms/{form_id}/submit")
def submit(
    form_id: int, body: VersionOnly, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.form_out(db, service.submit_for_review(db, principal, form_id, body.version))


@router.post("/forms/{form_id}/return")
def return_form(
    form_id: int, body: ReturnIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.form_out(db, service.return_to_author(db, principal, form_id, body.version, body.comment))


@router.post("/forms/{form_id}/publish")
def publish(
    form_id: int, body: PublishIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.form_out(db, service.publish(db, principal, form_id, body))


@router.post("/forms/{form_id}/extend")
def extend(
    form_id: int, body: WindowIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.form_out(db, service.extend(db, principal, form_id, body))


@router.post("/forms/{form_id}/close")
def close(
    form_id: int, body: CloseIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.form_out(db, service.close(db, principal, form_id, body))


@router.get("/forms/{form_id}/comments")
def comments(form_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.comments(db, principal, form_id)
