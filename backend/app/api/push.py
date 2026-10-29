from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal
from app.config import get_settings
from app.db import get_db
from app.errors import not_found
from app.push import service
from app.push.service import EndpointIn, SubscriptionIn

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/key")
def public_key(_: Principal = Depends(current_principal)):
    """The VAPID public key browsers need to subscribe; 404 when push is not set up."""
    if not service.configured():
        raise not_found()
    return {"public_key": get_settings().vapid_public_key}


@router.post("/subscriptions", status_code=204)
def subscribe(body: SubscriptionIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    service.subscribe(db, principal, body)


@router.post("/subscriptions/remove", status_code=204)
def unsubscribe(body: EndpointIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    service.unsubscribe(db, principal, body.endpoint)
