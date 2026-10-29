from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.scoring import service
from app.scoring.service import RecalculateIn, RuleSetIn, RuleSetUpdate, VersionIn

router = APIRouter(prefix="/api", tags=["scoring"])


@router.get("/forms/{form_id}/rule-sets")
def list_rule_sets(form_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.list_rule_sets(db, principal, form_id)


@router.post("/forms/{form_id}/rule-sets", status_code=201)
def create_rule_set(
    form_id: int, body: RuleSetIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.rule_set_out(db, service.create_rule_set(db, principal, form_id, body), with_checks=True)


@router.get("/rule-sets/{rule_set_id}")
def get_rule_set(rule_set_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.rule_set_out(db, service.get_rule_set(db, principal, rule_set_id), with_checks=True)


@router.patch("/rule-sets/{rule_set_id}")
def update_rule_set(
    rule_set_id: int,
    body: RuleSetUpdate,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    return service.rule_set_out(db, service.update_rule_set(db, principal, rule_set_id, body), with_checks=True)


@router.post("/rule-sets/{rule_set_id}/activate")
def activate(
    rule_set_id: int, body: VersionIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.rule_set_out(db, service.activate(db, principal, rule_set_id, body), with_checks=True)


@router.post("/rule-sets/{rule_set_id}/discard")
def discard(
    rule_set_id: int, body: VersionIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.rule_set_out(db, service.discard_rule_set(db, principal, rule_set_id, body))


@router.get("/forms/{form_id}/recalculations")
def list_recalculations(form_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.list_recalculations(db, principal, form_id)


@router.post("/forms/{form_id}/recalculations", status_code=202)
def recalculate(
    form_id: int, body: RecalculateIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.recalculation_out(db, service.recalculate(db, principal, form_id, body))
