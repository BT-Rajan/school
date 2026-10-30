"""Live updates (FR-RT1 to FR-RT3): scope is enforced at the broadcaster."""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import realtime as realtime_api
from app.db import session_factory
from app.models import Notification
from app.notifications import service as notify
from app.realtime.broadcaster import broadcaster

from .test_documents import act, create, w  # noqa: F401

ORIGIN = {"origin": "https://sces.test"}


def socket(client):
    ws = client.websocket_connect("/api/realtime/ws", headers=ORIGIN)
    ws.__enter__()
    assert ws.receive_json() == {"type": "ready"}
    return ws


def poke(user_id: int) -> None:
    """A notification for one user: a marker that everything before it was delivered."""
    with session_factory()() as db:
        notify.notify(db, user_id, "report_forwarded", {"report_code": "X", "school": "S"})
        db.commit()
    broadcaster.wait_idle()


def test_events_reach_only_those_who_may_see_them(w):
    a_ws, b_ws, admin_ws, head_ws = (socket(w[k]) for k in ("a", "b", "admin1", "head"))
    try:
        doc = create(w["a"], w).json()
        act(w["a"], doc, "submit")
        broadcaster.wait_idle()
        changed = {"type": "changed", "entity": "document", "id": str(doc["id"])}
        assert a_ws.receive_json() == changed
        # Admins see drafts too: the creation, the submission, and the notification about it.
        received = [admin_ws.receive_json() for _ in range(3)]
        assert received.count(changed) == 2 and {"type": "notification"} in received
        # The second supervisor of the same school, and the Cluster Head before any forward,
        # hear nothing: the first thing each receives is the marker sent afterwards.
        for client_ws, user in ((b_ws, w["user_b"]), (head_ws, w["head_user"])):
            poke(user.id)
            assert client_ws.receive_json() == {"type": "notification"}
    finally:
        for ws in (a_ws, b_ws, admin_ws, head_ws):
            ws.__exit__(None, None, None)


def test_rolled_back_changes_are_never_announced(w):
    a_ws = socket(w["a"])
    try:
        with session_factory()() as db:
            notify.notify(db, w["user_a"].id, "report_forwarded", {"report_code": "X", "school": "S"})
            db.rollback()
        poke(w["user_a"].id)
        assert a_ws.receive_json() == {"type": "notification"}
        with session_factory()() as db:
            assert db.query(Notification).filter(Notification.user_id == w["user_a"].id).count() == 1
    finally:
        a_ws.__exit__(None, None, None)


def test_other_sites_and_signed_out_browsers_cannot_listen(w, new_client):
    with pytest.raises(WebSocketDisconnect) as refused:
        with w["a"].websocket_connect("/api/realtime/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert refused.value.code == 4403
    with pytest.raises(WebSocketDisconnect) as refused:
        with new_client().websocket_connect("/api/realtime/ws", headers=ORIGIN) as ws:
            ws.receive_json()
    assert refused.value.code == 4401


def test_the_connection_closes_when_the_session_ends(w, monkeypatch):
    monkeypatch.setattr(realtime_api, "KEEPALIVE_SECONDS", 0.05)
    monkeypatch.setattr(realtime_api, "RECHECK_SECONDS", 0.05)
    ws = socket(w["a"])
    try:
        assert ws.receive_json() == {"type": "ping"}
        w["a"].post("/api/auth/logout")
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(10):
                ws.receive_json()
        assert closed.value.code == 4401
    finally:
        ws.__exit__(None, None, None)


def test_server_sent_events_fallback(w):
    with w["a"].stream("GET", "/api/realtime/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = response.iter_lines()
        assert next(lines) == "retry: 3000"
        assert next(lines) == ""
        assert next(lines) == 'data: {"type": "ready"}'


def test_the_bulk_audience_matches_the_rule_for_everyone(w):
    """Live updates decide who hears about a report for everyone at once (documents.access.audience).
    It must agree with can_access, the rule every screen uses, for every user and report state."""
    from sqlalchemy import select

    from app.auth.deps import Principal
    from app.documents import access
    from app.models import Document, User, UserStatus

    a, b, admin = w["a"], w["b"], w["admin1"]
    create(a, w)  # a draft
    submitted = create(a, w).json()
    act(a, submitted, "submit")
    forwarded = create(b, w).json()
    act(b, forwarded, "submit")
    assert admin.post(f"/api/documents/{forwarded['id']}/forward", json={"note": "x"}).status_code == 200
    revoked = create(a, w, school=w["school_y"]).json()
    act(a, revoked, "submit")
    admin.post(f"/api/documents/{revoked['id']}/forward", json={"note": "x"})
    admin.post(f"/api/documents/{revoked['id']}/revoke-forward")
    deleted = create(a, w).json()
    act(a, deleted, "delete")
    withdrawn = create(b, w).json()
    act(b, withdrawn, "submit")
    act(b, b.get(f"/api/documents/{withdrawn['id']}").json(), "withdraw")
    with session_factory()() as db:
        users = list(db.execute(select(User).where(User.status == UserStatus.ACTIVE)).scalars())
        principals = [Principal(u, None) for u in users]
        documents = list(db.execute(select(Document.id)).scalars())
        assert len(documents) == 6
        for document_id in documents:
            expected = {p.user.id for p in principals if access.can_access(db, p, document_id)}
            assert access.audience(db, principals, document_id) == expected
            assert expected  # every report has someone who may see it: the admins
        # The cases are real: the Cluster Head hears about the forwarded report only, and the
        # owner no longer hears about the deleted one.
        head, owner_a = w["head_user"].id, w["user_a"].id
        assert head in access.audience(db, principals, forwarded["id"])
        assert head not in access.audience(db, principals, revoked["id"])
        assert owner_a in access.audience(db, principals, submitted["id"])
        assert owner_a not in access.audience(db, principals, deleted["id"])
