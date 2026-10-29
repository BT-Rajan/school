"""Server support for offline phones (FR-D6, FR-PW5, FR-PW11, FR-PW13)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.files import resumable
from app.models import AuditLog, FormVersion, StoredFile, UploadSession

from .test_evaluations import GOOD, TODAY, world  # noqa: F401
from .test_files import pdf_bytes


def start_upload(client, content, key=None, name="scan.pdf"):
    r = client.post("/api/uploads", json={"client_key": key or uuid.uuid4().hex, "name": name, "size": len(content)})
    assert r.status_code == 201, r.text
    return r.json()


def put(client, upload_id, offset, data):
    return client.put(
        f"/api/uploads/{upload_id}/chunks",
        params={"offset": offset},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_a_dropped_upload_resumes_and_a_replay_never_duplicates(world):
    a = world["a"]
    content = pdf_bytes(3, extra_text=uuid.uuid4().hex.encode())
    key = uuid.uuid4().hex
    upload = start_upload(a, content, key)
    half = len(content) // 2
    assert put(a, upload["id"], 0, content[:half]).json()["received"] == half
    # The connection drops; the phone asks where it got to and carries on from there.
    assert a.get(f"/api/uploads/{upload['id']}").json()["received"] == half
    # A piece sent twice is acknowledged once; a piece out of order is refused with the offset.
    assert put(a, upload["id"], 0, content[:half]).json()["received"] == half
    wrong = put(a, upload["id"], half + 5, content[half + 5 :])
    assert wrong.status_code == 409 and wrong.json()["error"]["detail"] == {"received": half}
    assert a.post(f"/api/uploads/{upload['id']}/complete").json()["error"]["code"] == "upload_incomplete"
    put(a, upload["id"], half, content[half:])
    stored = a.post(f"/api/uploads/{upload['id']}/complete").json()
    assert stored["pages"] == 3 and stored["status"] == "pending"
    # Replaying the whole upload, as an offline queue would, returns the same file.
    again = start_upload(a, content, key)
    assert again["id"] == upload["id"] and again["file_id"] == stored["id"]
    assert a.post(f"/api/uploads/{upload['id']}/complete").json()["id"] == stored["id"]
    with session_factory()() as db:
        assert len(db.execute(select(StoredFile)).scalars().all()) == 1


def test_pieces_are_encrypted_and_private(world, file_store):
    a, b = world["a"], world["b"]
    marker = uuid.uuid4().hex.encode()
    content = pdf_bytes(1, extra_text=marker)
    upload = start_upload(a, content)
    put(a, upload["id"], 0, content)
    with session_factory()() as db:
        chunk_key = db.get(UploadSession, upload["id"]).chunks[0]
    assert marker not in file_store.get(chunk_key)
    # Another user cannot see, extend or complete it.
    assert b.get(f"/api/uploads/{upload['id']}").status_code == 404
    assert put(b, upload["id"], 0, content).status_code == 404
    assert b.post(f"/api/uploads/{upload['id']}/complete").status_code == 404
    # Pieces are deleted once the upload completes.
    a.post(f"/api/uploads/{upload['id']}/complete")
    assert chunk_key not in set(file_store.keys())


def test_abandoned_uploads_are_pruned(world, file_store):
    content = pdf_bytes(1, extra_text=b"old")
    upload = start_upload(world["a"], content)
    put(world["a"], upload["id"], 0, content)
    clock.freeze(datetime(2026, 11, 13, 6, 0))
    with session_factory()() as db:
        assert resumable.prune(db) == 1
        assert db.get(UploadSession, upload["id"]) is None
    assert list(file_store.keys()) == []


def test_offline_submission_after_the_form_closed(world):
    """FR-PW13: accepted if the visit was inside the form's window, else the draft stays."""
    a = world["a"]
    e = a.post(
        "/api/evaluations",
        json={"form_id": world["form_id"], "school_id": world["school"].id, "visit_date": str(TODAY)},
    ).json()
    e = a.patch(f"/api/evaluations/{e['id']}", json={"version": e["version"], "sections": {"visit": GOOD}}).json()
    late = a.post(
        "/api/evaluations",
        json={"form_id": world["form_id"], "school_id": world["school"].id, "visit_date": str(TODAY)},
    ).json()
    late = a.patch(
        f"/api/evaluations/{late['id']}", json={"version": late["version"], "sections": {"visit": GOOD}}
    ).json()
    with session_factory()() as db:
        form = db.get(FormVersion, world["form_id"])
        form.end_date = TODAY
        db.commit()
    clock.freeze(datetime(2026, 11, 11, 6, 0))  # the next day: the form has closed
    login_again(world)
    a = world["a"]
    # Typed online after closing: refused, and the draft is kept.
    r = a.post(f"/api/evaluations/{late['id']}/submit", json={"version": late["version"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "form_closed"
    # Queued offline yesterday, sent today: the visit was in the window, so it is accepted.
    device_time = "2026-11-10T08:30:00Z"
    r = a.post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"], "device_time": device_time})
    assert r.status_code == 200, r.text


def test_device_clock_far_off_is_flagged(world):
    a = world["a"]
    e = a.post(
        "/api/evaluations",
        json={"form_id": world["form_id"], "school_id": world["school"].id, "visit_date": str(TODAY)},
    ).json()
    e = a.patch(f"/api/evaluations/{e['id']}", json={"version": e["version"], "sections": {"visit": GOOD}}).json()
    skewed = (datetime(2026, 11, 10, 6, 0) - timedelta(days=3)).isoformat() + "Z"
    assert (
        a.post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"], "device_time": skewed}).status_code
        == 200
    )
    with session_factory()() as db:
        flagged = db.execute(select(AuditLog).where(AuditLog.action == "evaluation.clock_skew")).scalar_one()
    assert flagged.severity == "warning"


def login_again(world):
    """Jumping the clock ends idle sessions; sign the supervisor back in."""
    from .helpers import login

    a = world["new_client"]()
    login(a, world["outbox"], "a@example.org")
    world["a"] = a
