"""Web Push (FR-N3): subscriptions per session, queued sends, and refused endpoints."""

import base64
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.config import get_settings
from app.db import session_factory
from app.models import MfaMethod, PushMessage, PushSubscription, Role
from app.notifications import service as notify
from app.push import service as push

from .helpers import signed_in

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def browser_keys() -> dict:
    """What a browser's PushManager hands over: its ECDH public key and an auth secret."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"p256dh": b64(public), "auth": b64(os.urandom(16))}


@pytest.fixture
def vapid(monkeypatch):
    public, private = push.generate_vapid_keys()
    settings = get_settings()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    monkeypatch.setattr(settings, "vapid_private_key", private)
    return public


@pytest.fixture
def sent(monkeypatch):
    """Capture what would go to the push service, answering with the given status."""
    calls = []
    status = {"code": 201}

    class Response:
        def __init__(self, code):
            self.status_code = code
            self.text = ""
            self.reason = "Gone" if code == 410 else "Created"
            self.headers = {}

    def fake_post(url, data=None, headers=None, timeout=None, **_):
        calls.append({"url": url, "data": data, "headers": headers})
        return Response(status["code"])

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    return calls, status


def test_push_is_off_until_keys_are_set(new_client, outbox):
    client, _ = signed_in(new_client, outbox, Role.SUPERVISOR, "s@example.org")
    assert client.get("/api/push/key").status_code == 404
    r = client.post("/api/push/subscriptions", json={"endpoint": ENDPOINT, "keys": browser_keys()})
    assert r.json()["error"]["code"] == "push_not_configured"


def test_subscribe_send_and_sign_out(new_client, outbox, vapid, sent):
    calls, status = sent
    client, user = signed_in(new_client, outbox, Role.SUPERVISOR, "s@example.org")
    assert client.get("/api/push/key").json() == {"public_key": vapid}
    # Only the browsers' push services: never an internal address.
    for bad in ("http://fcm.googleapis.com/x", "https://10.0.0.5/push", "https://fcm.googleapis.com.evil.org/x"):
        r = client.post("/api/push/subscriptions", json={"endpoint": bad, "keys": browser_keys()})
        assert r.json()["error"]["code"] == "push_endpoint_refused", bad
    assert (
        client.post("/api/push/subscriptions", json={"endpoint": ENDPOINT, "keys": browser_keys()}).status_code == 204
    )

    with session_factory()() as db:
        notify.notify(
            db, user.id, "report_forwarded", {"report_code": "MOE-SV-01", "school": "Al-Nahda", "document_id": 7}
        )
        db.commit()
        assert push.dispatch(db) == 1
    [call] = calls
    assert call["url"] == ENDPOINT
    assert call["headers"]["content-encoding"] == "aes128gcm"
    assert call["headers"]["authorization"].startswith("vapid ")
    # The body is encrypted for that browser: the report details never travel in the clear.
    assert b"MOE-SV-01" not in call["data"]

    # A push service that says the subscription is gone: it is removed.
    status["code"] = 410
    with session_factory()() as db:
        notify.notify(db, user.id, "report_forwarded", {"report_code": "X", "school": "S"})
        db.commit()
        push.dispatch(db)
        assert db.execute(select(PushSubscription)).first() is None

    # Signing out removes this session's subscription.
    status["code"] = 201
    client2, _ = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "h@example.org")
    client2.post("/api/push/subscriptions", json={"endpoint": ENDPOINT + "2", "keys": browser_keys()})
    client2.post("/api/auth/logout")
    with session_factory()() as db:
        assert db.execute(select(PushSubscription)).first() is None


def test_push_follows_the_users_choice(new_client, outbox, vapid, sent):
    client, user = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "a@example.org", mfa=MfaMethod.TOTP)
    client.post("/api/push/subscriptions", json={"endpoint": ENDPOINT, "keys": browser_keys()})
    r = client.put(
        "/api/notifications/preferences", json={"type": "report_submitted", "channel": "push", "enabled": False}
    )
    assert r.status_code == 204
    with session_factory()() as db:
        notify.notify(db, user.id, "report_submitted", {"report_code": "X", "school": "S", "supervisor": "N"})
        db.commit()
        assert db.execute(select(PushMessage)).first() is None
    prefs = {p["type"]: p for p in client.get("/api/notifications/preferences").json()}
    assert prefs["report_submitted"]["push"] is False and prefs["report_submitted"]["email"] is True
