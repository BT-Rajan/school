from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.district import get_district
from app.errors import AppError
from app.evaluations import service
from app.evaluations.service import AmendIn, CancelIn, SaveIn, StartIn, SubmitIn
from app.models import FormVersion
from app.pdf.report import render_evaluation

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


@router.post("", status_code=201)
def start(body: StartIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.evaluation_out(db, service.start(db, principal, body))


@router.get("")
def list_evaluations(
    status: str | None = None,
    school_id: int | None = None,
    form_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    return service.list_evaluations(
        db, principal, status=status, school_id=school_id, form_id=form_id, page=page, page_size=page_size
    )


@router.get("/{evaluation_id}")
def get_evaluation(
    evaluation_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.evaluation_out(db, service.get_evaluation(db, principal, evaluation_id))


@router.patch("/{evaluation_id}")
def save(
    evaluation_id: int, body: SaveIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.evaluation_out(db, service.save(db, principal, evaluation_id, body))


@router.post("/{evaluation_id}/submit")
def submit(
    evaluation_id: int, body: SubmitIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.evaluation_out(db, service.submit(db, principal, evaluation_id, body))


@router.post("/{evaluation_id}/amend")
def amend(
    evaluation_id: int, body: AmendIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.evaluation_out(db, service.amend(db, principal, evaluation_id, body))


@router.post("/{evaluation_id}/cancel")
def cancel(
    evaluation_id: int, body: CancelIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.evaluation_out(db, service.cancel(db, principal, evaluation_id, body))


@router.get("/{evaluation_id}/amendments")
def amendments(evaluation_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.amendments(db, principal, evaluation_id)


@router.get("/{evaluation_id}/pdf")
def pdf(
    evaluation_id: int,
    locale: str = Query(default="en", pattern="^(en|ar)$"),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    e = service.get_evaluation(db, principal, evaluation_id)
    if e.status not in ("submitted", "amended"):
        raise AppError(409, "evaluation_not_submitted")
    data = service.evaluation_out(db, e)
    district = get_district(db)
    body = render_evaluation(
        data,
        db.get(FormVersion, e.form_version_id).schema,
        locale,
        district.name_ar if locale == "ar" else district.name_en,
    )
    audit.record(db, "evaluation.pdf_generated", entity_type="evaluation", entity_id=e.id, after={"locale": locale})
    db.commit()
    name = f"{data['report']['code']}-{data['report']['version_code']}-{e.id}.pdf".replace("/", "-")
    return Response(
        body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"},
    )
