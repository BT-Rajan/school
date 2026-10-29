from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.documents import access, service
from app.documents.service import (
    CreateIn,
    ForwardIn,
    LinkIn,
    NewVersionIn,
    ReturnIn,
    ReviewIn,
    SubmitIn,
    UpdateIn,
    VersionIn,
)
from app.evaluations import service as evaluations

router = APIRouter(prefix="/api", tags=["documents"])


def _out(db: Session, principal: Principal, d) -> dict:
    return service.document_out(db, principal, d, full=True)


@router.post("/documents", status_code=201)
def create(body: CreateIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _out(db, principal, service.create(db, principal, body))


@router.get("/documents")
def list_documents(
    q: str | None = Query(default=None, max_length=100),
    status: str | None = None,
    supervisor_id: int | None = None,
    cluster_id: int | None = None,
    school_id: int | None = None,
    report_code: str | None = None,
    report_version_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_archived: bool = False,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    return service.list_documents(
        db,
        principal,
        q=q,
        status=status,
        supervisor_id=supervisor_id,
        cluster_id=cluster_id,
        school_id=school_id,
        report_code=report_code,
        report_version_id=report_version_id,
        date_from=date_from,
        date_to=date_to,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )


@router.get("/documents/dashboard")
def dashboard(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.supervisor_dashboard(db, principal)


@router.get("/documents/{document_id}")
def get_document(document_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _out(db, principal, access.get_visible(db, principal, document_id))


@router.patch("/documents/{document_id}")
def update(
    document_id: int, body: UpdateIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return _out(db, principal, service.update(db, principal, document_id, body))


@router.post("/documents/{document_id}/versions")
def new_version(
    document_id: int,
    body: NewVersionIn,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    return _out(db, principal, service.new_version(db, principal, document_id, body))


def _action(name: str, fn, model):
    def endpoint(
        document_id: int, body: model, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
    ):
        return _out(db, principal, fn(db, principal, document_id, body))

    router.add_api_route(f"/documents/{{document_id}}/{name}", endpoint, methods=["POST"], name=f"document_{name}")


_action("submit", service.submit, SubmitIn)
_action("withdraw", service.withdraw, VersionIn)
_action("delete", service.delete, VersionIn)
_action("acknowledge", service.acknowledge, ReviewIn)
_action("return", service.return_, ReturnIn)
_action("forward", service.forward, ForwardIn)


@router.post("/documents/{document_id}/revoke-forward")
def revoke_forward(document_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _out(db, principal, service.revoke_forward(db, principal, document_id))


@router.post("/documents/{document_id}/restore")
def restore(document_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _out(db, principal, service.restore(db, principal, document_id))


@router.post("/documents/{document_id}/archive")
def archive(document_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _out(db, principal, service.archive(db, principal, document_id))


@router.post("/documents/{document_id}/link")
def link(
    document_id: int, body: LinkIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    result = service.link(db, principal, document_id, body)
    return {"url": result.url, "expires_at": result.expires_at}


@router.get("/documents/{document_id}/access")
def access_history(document_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.access_history(db, principal, document_id)


@router.get("/evaluations/{evaluation_id}/documents")
def evaluation_documents(
    evaluation_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    evaluations.get_evaluation(db, principal, evaluation_id)
    return service.linked_documents(db, principal, evaluation_id)
