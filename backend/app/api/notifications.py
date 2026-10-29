from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.notifications import service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return service.list_for(db, principal.user.id, unread_only)


@router.post("/{notification_id}/read", status_code=204)
def mark_read(notification_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    service.mark_read(db, principal.user.id, notification_id)


@router.post("/read-all", status_code=204)
def mark_all_read(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    service.mark_read(db, principal.user.id)


@router.get("/preferences")
def preferences(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.preferences(db, principal.user.id)


class PreferenceIn(BaseModel):
    type: str
    channel: str
    enabled: bool


@router.put("/preferences", status_code=204)
def set_preference(
    body: PreferenceIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    service.set_preference(db, principal.user.id, body.type, body.channel, body.enabled)
