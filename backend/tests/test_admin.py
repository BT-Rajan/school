import csv
import io
import json
from datetime import timedelta

from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.models import AuditLog

from .test_documents import scan, submitted, w  # noqa: F401 - w is the shared fixture
from .test_reporting import evaluation


def settings(client):
    return client.get("/api/admin/settings").json()


def patch(client, **body):
    return client.patch("/api/admin/settings", json={"version": settings(client)["version"], **body})


# Settings (FR-AD1) ---------------------------------------------------------------------------


def test_admin_settings_cover_the_district(w):
    admin = w["admin1"]
    current = settings(admin)
    assert {"code", "default_locale", "time_zone", "mail_provider", "notice_types"} <= set(current)
    r = patch(
        admin,
        code="KW-HAW",
        time_zone="Asia/Riyadh",
        settings={
            "enabled_locales": ["en", "ar"],
            "totp_required_roles": ["district_admin", "cluster_head"],
            "audit_retention_years": 10,
            "mail_sender_name": "Hawalli Schools",
            "digest_time": "17:30",
        },
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["code"], got["time_zone"]) == ("KW-HAW", "Asia/Riyadh")
    assert got["settings"]["totp_required_roles"] == ["cluster_head", "district_admin"]
    assert got["settings"]["mail_sender_name"] == "Hawalli Schools"
    for bad in (
        {"settings": {"enabled_locales": ["ar"]}},
        {"settings": {"totp_required_roles": ["cluster_head"]}},
        {"settings": {"digest_time": "25:00"}},
        {"settings": {"audit_retention_years": 0}},
        {"settings": {"mail_sender_name": "x\r\nBcc: someone"}},
        {"settings": {"notification_defaults": {"nope": {"email": False}}}},
        {"time_zone": "Mars/Olympus"},
    ):
        assert patch(admin, **bad).json()["error"]["code"] == "setting_invalid", bad
    # The default language must be one that is enabled.
    patch(admin, default_locale="ar")
    assert patch(admin, settings={"enabled_locales": ["en"]}).json()["error"]["code"] == "setting_invalid"
    assert w["head"].get("/api/admin/settings").status_code == 403
    with session_factory()() as db:
        changed = db.execute(select(AuditLog).where(AuditLog.action == "settings.updated")).scalars().all()
    assert changed and changed[0].after["code"] == "KW-HAW"


def test_district_logo(w, client):
    admin = w["admin1"]
    png = io.BytesIO()
    Image.new("RGB", (64, 64), (20, 90, 160)).save(png, "PNG")
    r = admin.put("/api/admin/logo", files={"file": ("logo.png", png.getvalue())})
    assert r.status_code == 200 and r.json()["logo"] is True, r.text
    scan()
    # Anyone may fetch it, signed in or not: it is on the sign-in page.
    logo = client.get("/api/district/logo")
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"
    assert client.get("/api/district").json()["logo"] is True
    from .test_files import pdf_bytes

    assert (
        admin.put("/api/admin/logo", files={"file": ("logo.pdf", pdf_bytes(1))}).json()["error"]["code"] == "logo_type"
    )


def test_notification_defaults_apply_until_a_user_chooses(w):
    admin = w["admin1"]
    before = {p["type"]: p for p in w["a"].get("/api/notifications/preferences").json()}
    kind = next(iter(before))
    assert before[kind]["email"] is True
    r = patch(admin, settings={"notification_defaults": {kind: {"email": False}}})
    assert r.status_code == 200, r.text
    after = {p["type"]: p for p in w["a"].get("/api/notifications/preferences").json()}
    assert after[kind]["email"] is False and after[kind]["in_app"] is True


# Audit viewer (FR-L5) and failed sign-ins (FR-AD2) -------------------------------------------


def test_audit_viewer_filters_and_audited_export(w, client):
    admin = w["admin1"]
    doc = submitted(w)
    assert w["a"].get("/api/admin/audit").status_code == 403
    found = admin.get("/api/admin/audit", params={"entity_type": "document", "entity_id": str(doc["id"])}).json()
    assert found["total"] >= 2 and {e["action"] for e in found["items"]} >= {"document.uploaded", "document.submitted"}
    assert all(e["actor"]["name"] == "a" for e in found["items"])
    assert found["retention_years"] == 7 and found["past_retention"] == 0
    prefix = admin.get("/api/admin/audit", params={"action": "document."}).json()
    assert prefix["total"] == found["total"] and "document.uploaded" in prefix["actions"]
    with session_factory()() as db:
        a_id = db.execute(select(AuditLog.actor_id).where(AuditLog.action == "document.uploaded")).scalar_one()
    mine = admin.get("/api/admin/audit", params={"actor_id": a_id, "page_size": 200}).json()
    assert mine["items"] and all(e["actor"]["id"] == a_id for e in mine["items"])
    today = clock.local_date("Asia/Kuwait")
    assert admin.get("/api/admin/audit", params={"date_to": str(today - timedelta(days=1))}).json()["total"] == 0

    r = admin.get("/api/admin/audit/export", params={"format": "csv", "action": "document."})
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:3] == ["Sequence", "Time (UTC)", "Actor ID"] and len(rows) == found["total"] + 1
    r = admin.get("/api/admin/audit/export", params={"format": "xlsx", "locale": "ar"})
    assert load_workbook(io.BytesIO(r.content)).active.sheet_view.rightToLeft is True
    with session_factory()() as db:
        exports = db.execute(select(AuditLog).where(AuditLog.action == "audit.exported")).scalars().all()
    assert [e.after["format"] for e in exports] == ["csv", "xlsx"]
    assert exports[0].after["filters"] == {"action": "document."}

    client.post("/api/auth/login", json={"email": "a@example.org", "password": "wrong password here"})
    failed = admin.get("/api/admin/failed-sign-ins").json()
    assert failed[0]["action"] == "login.failed" and failed[0]["user"]["email"] == "a@example.org"


# Support view (FR-AD3) ----------------------------------------------------------------------


def test_support_view_is_read_only_audited_and_shown_to_the_user(w):
    admin, a = w["admin1"], w["admin1"]
    own = evaluation(w, w["a"], submit=False)
    found = admin.get("/api/admin/support-users", params={"q": "a@example"}).json()
    target = next(u for u in found if u["email"] == "a@example.org")
    assert all(u["role"] != "district_admin" for u in found)
    assert (
        admin.post("/api/admin/support-sessions", json={"user_id": target["id"], "reason": "short"}).status_code == 422
    )
    with session_factory()() as db:
        from app.models import User

        other_admin = db.execute(select(User).where(User.email == "admin2@example.org")).scalar_one().id
    r = admin.post("/api/admin/support-sessions", json={"user_id": other_admin, "reason": "Checking their screen"})
    assert r.json()["error"]["code"] == "support_not_for_admins"
    s = admin.post(
        "/api/admin/support-sessions", json={"user_id": target["id"], "reason": "Cannot find her draft"}
    ).json()
    view = {"X-Support-Session": str(s["id"])}
    me = a.get("/api/auth/me", headers=view).json()
    assert me["email"] == "a@example.org" and me["support_view"] == {"admin": "Mariam"}
    listed = a.get("/api/evaluations", headers=view).json()
    assert [e["id"] for e in listed["items"]] == [own["id"]]
    # Nothing can be changed, sent or downloaded through it.
    r = a.post(f"/api/evaluations/{own['id']}/submit", headers=view, json={"version": own["version"]})
    assert r.json()["error"]["code"] == "support_read_only"
    # Only the admin who started it can use it.
    assert w["admin2"].get("/api/auth/me", headers=view).json()["error"]["code"] == "support_session_invalid"
    assert w["b"].get("/api/auth/me", headers=view).json()["error"]["code"] == "support_session_invalid"
    with session_factory()() as db:
        views = db.execute(select(AuditLog).where(AuditLog.action == "support.viewed")).scalars().all()
        refused = db.execute(select(AuditLog).where(AuditLog.action == "permission.denied")).scalars().all()
    assert len(views) == 2 and {v.after["path"] for v in views} == {"/api/auth/me", "/api/evaluations"}
    assert [r.after["reason"] for r in refused] == ["support_read_only"]
    assert all(v.actor_role == "district_admin" for v in views)
    # While it is open, the user is not told yet; once it ends, they are, once.
    assert w["a"].get("/api/auth/me").json()["support_notices"] == []
    ended = admin.post(f"/api/admin/support-sessions/{s['id']}/end").json()
    assert ended["active"] is False and ended["views"] == 2
    assert a.get("/api/auth/me", headers=view).json()["error"]["code"] == "support_session_invalid"
    notices = w["a"].get("/api/auth/me").json()["support_notices"]
    assert [(n["admin"], n["reason"]) for n in notices] == [("Mariam", "Cannot find her draft")]
    assert w["a"].post("/api/auth/me/support-notices/seen").status_code == 204
    assert w["a"].get("/api/auth/me").json()["support_notices"] == []


def test_support_view_expires_after_thirty_minutes(w):
    admin = w["admin1"]
    target = next(u for u in admin.get("/api/admin/support-users", params={"q": "b@example"}).json())
    s = admin.post(
        "/api/admin/support-sessions", json={"user_id": target["id"], "reason": "Checking assignments", "minutes": 31}
    )
    assert s.status_code == 422
    s = admin.post(
        "/api/admin/support-sessions", json={"user_id": target["id"], "reason": "Checking assignments"}
    ).json()
    clock.freeze(clock.now() + timedelta(minutes=31))
    r = admin.get("/api/auth/me", headers={"X-Support-Session": str(s["id"])})
    assert r.json()["error"]["code"] == "support_session_invalid"


# Per-person export (FR-AD4) -----------------------------------------------------------------


def test_everything_held_about_one_person(w):
    admin = w["admin1"]
    submitted(w)
    evaluation(w, w["a"], submit=True)
    with session_factory()() as db:
        from app.models import User

        a_id = db.execute(select(User.id).where(User.email == "a@example.org")).scalar_one()
    assert w["head"].get(f"/api/admin/users/{a_id}/export").status_code == 403
    r = admin.get(f"/api/admin/users/{a_id}/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = json.loads(r.content)
    assert data["profile"]["email"] == "a@example.org"
    assert len(data["evaluations"]) == 1 and data["evaluations"][0]["sections"]
    assert len(data["documents"]) == 1 and data["documents"][0]["versions"][0]["file"]["sha256"]
    assert len(data["assignments"]) == 2 and data["sessions"] and data["audit_trail"]
    text = r.content.decode()
    for secret in ("password_hash", "totp_secret", "token_hash", "wrapped_key", "storage_key"):
        assert secret not in text
    with session_factory()() as db:
        entry = db.execute(select(AuditLog).where(AuditLog.action == "person.exported")).scalar_one()
    assert entry.entity_id == str(a_id) and entry.after["contents"]["evaluations"] == 1
