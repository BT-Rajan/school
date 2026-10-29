"""Account administration: District Admins, Cluster Heads, and account actions."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.auth import service as auth
from app.auth.deps import Principal, admin_only, structure_managers
from app.db import get_db
from app.models import Role, User
from app.structure import people
from app.structure.schemas import PersonUpdate, StaffIn

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/admins")
def list_admins(_: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return people.list_users(db, Role.DISTRICT_ADMIN)


@router.post("/admins", status_code=201)
def create_admin(body: StaffIn, principal: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return people.user_out(people.create_staff(db, principal, Role.DISTRICT_ADMIN, body))


@router.get("/cluster-heads")
def list_cluster_heads(_: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return people.list_users(db, Role.CLUSTER_HEAD)


@router.post("/cluster-heads", status_code=201)
def create_cluster_head(body: StaffIn, principal: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return people.user_out(people.create_staff(db, principal, Role.CLUSTER_HEAD, body))


@router.patch("/users/{user_id}")
def update_staff(user_id: int, body: PersonUpdate, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return people.user_out(people.update_staff(db, user_id, body))


@router.get("/admin/locked-accounts")
def locked_accounts(_: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    """FR-AD2."""
    users = db.execute(select(User).where(User.locked_until > clock.now()).order_by(User.locked_until)).scalars()
    return [people.user_out(u) | {"locked_until": u.locked_until} for u in users]


@router.post("/users/{user_id}/unlock", status_code=204)
def unlock(user_id: int, principal: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    auth.admin_unlock(db, people.get_managed_user(db, principal, user_id))


@router.post("/users/{user_id}/mfa-reset", status_code=204)
def mfa_reset(user_id: int, principal: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    auth.admin_reset_mfa(db, people.get_managed_user(db, principal, user_id))


@router.post("/users/{user_id}/resend-invitation", status_code=204)
def resend_invitation(user_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    people.resend_invitation(db, principal, user_id)


@router.post("/users/{user_id}/deactivate")
def deactivate(user_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return people.user_out(people.deactivate_user(db, principal, user_id))


@router.post("/users/{user_id}/reactivate")
def reactivate(user_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return people.user_out(people.reactivate_user(db, principal, user_id))
