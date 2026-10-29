from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.assignments import service
from app.assignments.service import AssignIn, ReassignIn, UnassignIn
from app.auth.deps import Principal, current_principal, require_roles, structure_managers
from app.db import get_db
from app.models import Role

router = APIRouter(prefix="/api", tags=["assignments"])
readers = require_roles(Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR)


@router.post("/assignments", status_code=201)
def assign(body: AssignIn, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return service.assignment_out(db, service.assign(db, principal, body))


@router.post("/assignments/{assignment_id}/end")
def unassign(
    assignment_id: int,
    body: UnassignIn,
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    return service.assignment_out(db, service.unassign(db, principal, assignment_id, body))


@router.post("/assignments/{assignment_id}/reassign", status_code=201)
def reassign(
    assignment_id: int,
    body: ReassignIn,
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    return service.assignment_out(db, service.reassign(db, principal, assignment_id, body))


@router.get("/assignments/history")
def history(
    school_id: int | None = None,
    supervisor_id: int | None = None,
    principal: Principal = Depends(readers),
    db: Session = Depends(get_db),
):
    return service.history(db, principal, school_id=school_id, supervisor_id=supervisor_id)


@router.get("/assignments/board")
def board(cluster_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return service.board(db, principal, cluster_id)


@router.get("/me/assignments")
def my_assignments(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.my_assignments(db, principal)
