"""Web Push for users who allow it on a device (FR-N3).

A browser subscribes for the session it is signed in with; signing out removes that
subscription, so a shared phone stops showing the previous user's notices. Notices
are queued here and sent by the worker, never during a request. A push carries the
same one-line text as the in-app notice: report ID, title and school, never content
(FR-N7).

The worker sends only to the browser vendors' push services. Any other endpoint is
refused, so a subscription cannot point the server at an internal address.
"""

import base64
import json
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import clock
from app.auth import service as auth
from app.auth.deps import Principal
from app.config import get_settings
from app.errors import invalid
from app.models import PushMessage, PushSubscription, User
from app.security import tokens

# The push services of Chrome and Android, Firefox, Edge and Safari on iPhone and Mac.
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    ".push.services.mozilla.com",
    ".notify.windows.com",
    "web.push.apple.com",
    ".push.apple.com",
)
MAX_ATTEMPTS = 5
TTL_SECONDS = 24 * 3600


class Keys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: Keys


class EndpointIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)


def configured() -> bool:
    settings = get_settings()
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def endpoint_allowed(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h.lstrip(".") or host.endswith(h) for h in PUSH_HOSTS if h)


def subscribe(db: Session, principal: Principal, body: SubscriptionIn) -> None:
    if not configured():
        raise invalid("push_not_configured")
    if not endpoint_allowed(body.endpoint):
        raise invalid("push_endpoint_refused")
    key = tokens.sha256(body.endpoint)
    existing = db.execute(select(PushSubscription).where(PushSubscription.endpoint_hash == key)).scalar_one_or_none()
    if existing is None:
        existing = PushSubscription(endpoint_hash=key, endpoint=body.endpoint)
        db.add(existing)
    # A shared phone: the browser now belongs to whoever is signed in.
    existing.user_id, existing.session_id = principal.user.id, principal.session.id
    existing.p256dh, existing.auth = body.keys.p256dh, body.keys.auth
    db.commit()


def unsubscribe(db: Session, principal: Principal, endpoint: str) -> None:
    db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint_hash == tokens.sha256(endpoint), PushSubscription.user_id == principal.user.id
        )
    )
    db.commit()


def forget_session(db: Session, session_id: int) -> None:
    """Called on sign-out."""
    db.execute(delete(PushSubscription).where(PushSubscription.session_id == session_id))


def _url(user: User, type_: str, payload: dict[str, Any]) -> str:
    if isinstance(payload.get("request_id"), int):
        return f"/requests/{payload['request_id']}"
    if isinstance(payload.get("document_id"), int):
        return f"/reports/{payload['document_id']}"
    if isinstance(payload.get("evaluation_id"), int):
        return f"/evaluations/{payload['evaluation_id']}"
    if isinstance(payload.get("form_id"), int):
        return f"/forms/{payload['form_id']}" if user.role in ("district_admin", "form_author") else "/evaluations"
    return "/notifications"


def queue(db: Session, user: User, type_: str, text: str, payload: dict[str, Any]) -> None:
    if not configured():
        return
    if db.execute(select(PushSubscription.id).where(PushSubscription.user_id == user.id)).first() is None:
        return
    db.add(PushMessage(user_id=user.id, payload={"body": text, "url": _url(user, type_, payload), "tag": type_}))


def send(subscription: PushSubscription, data: dict[str, Any]) -> int | None:
    """Send one push. Returns the push service's HTTP status when it refused."""
    from pywebpush import WebPushException, webpush

    settings = get_settings()
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(data, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=TTL_SECONDS,
            timeout=10,
        )
    except WebPushException as exc:
        return exc.response.status_code if exc.response is not None else 0
    return None


def dispatch(db: Session) -> int:
    """Worker: send queued pushes. Gone subscriptions are removed; failures retry."""
    sent = 0
    messages = db.execute(
        select(PushMessage).where(PushMessage.status == "queued").order_by(PushMessage.id).limit(200)
    ).scalars()
    for message in list(messages):
        subscriptions = db.execute(
            select(PushSubscription).where(PushSubscription.user_id == message.user_id)
        ).scalars()
        failed = None
        for subscription in list(subscriptions):
            if not auth.session_still_valid(db, subscription.session_id) or not endpoint_allowed(subscription.endpoint):
                db.delete(subscription)
                continue
            status = send(subscription, {"title": "SCES", **message.payload})
            if status in (404, 410):
                # The browser withdrew permission or the subscription expired.
                db.delete(subscription)
            elif status is not None:
                failed = f"push service answered {status}"
        message.attempts += 1
        if failed and message.attempts < MAX_ATTEMPTS:
            message.last_error = failed
        else:
            message.status = "failed" if failed else "sent"
            message.last_error = failed
            message.sent_at = clock.now()
            sent += 0 if failed else 1
        db.commit()
    return sent


def generate_vapid_keys() -> tuple[str, str]:
    """A new VAPID key pair: (public key for browsers, private key for the server), base64url."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")  # noqa: E731
    return encode(public), encode(private)
