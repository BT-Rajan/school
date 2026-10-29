"""Scanned report vault: the isolation and review rules of section 9 and the acceptance criteria in section 18."""

import io
import uuid
from datetime import datetime, timedelta

import pikepdf
import pytest
from PIL import Image
from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.files import service as files
from app.models import AuditLog, Cluster, FormVersion, MfaMethod, Role

from .helpers import (
    assign_direct,
    login,
    make_cluster,
    make_school,
    make_supervisor,
    publish_direct,
    sample_schema,
    seed_reference,
    signed_in,
    teacher_body,
)
from .test_files import pdf_bytes

TODAY = datetime(2026, 11, 10).date()


def scan():
    with session_factory()() as db:
        files.scan_pending(db)


def report_version_id(form_id: int) -> int:
    with session_factory()() as db:
        return db.get(FormVersion, form_id).ministry_report_version_id


@pytest.fixture
def w(new_client, outbox):
    clock.freeze(datetime(2026, 11, 10, 6, 0))  # 10/11/2026, 09:00 in Kuwait
    seed_reference()
    head, head_user = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head@example.org", staff_id="CH")
    other_head, other_head_user = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head2@example.org", staff_id="CH2")
    admin1, _ = signed_in(
        new_client, outbox, Role.DISTRICT_ADMIN, "admin1@example.org", name="Mariam", staff_id="A1", mfa=MfaMethod.TOTP
    )
    admin2, _ = signed_in(
        new_client, outbox, Role.DISTRICT_ADMIN, "admin2@example.org", name="Huda", staff_id="A2", mfa=MfaMethod.TOTP
    )
    teacher_client, _ = signed_in(new_client, outbox, Role.TEACHER, "teacher@example.org")
    author, _ = signed_in(new_client, outbox, Role.FORM_AUTHOR, "author@example.org", mfa=MfaMethod.TOTP)
    cluster, other_cluster = make_cluster("C1", head_user), make_cluster("C2", other_head_user)
    school_x, school_y = make_school(cluster, "SX"), make_school(cluster, "SY")
    sup_a, user_a = make_supervisor(cluster, "a@example.org", "SA")
    sup_b, user_b = make_supervisor(cluster, "b@example.org", "SB")
    for s in (sup_a, sup_b):
        assign_direct(s.id, school_x.id, TODAY - timedelta(days=60))
    assign_direct(sup_a.id, school_y.id, TODAY - timedelta(days=60))
    form_id = publish_direct(sample_schema(), TODAY - timedelta(days=5), TODAY + timedelta(days=20))
    mrv = report_version_id(form_id)
    a, b = new_client(), new_client()
    login(a, outbox, "a@example.org")
    login(b, outbox, "b@example.org")
    return dict(locals())


def upload(client, content=None, name="scan.pdf"):
    # Each scan is different, so the duplicate warning only fires when a test means it to.
    content = content or pdf_bytes(2, extra_text=uuid.uuid4().hex.encode())
    r = client.post("/api/files", files={"file": (name, content)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def create(client, w, school=None, **extra):
    body = {
        "file_ids": [upload(client)],
        "ministry_report_version_id": w["mrv"],
        "school_id": (school or w["school_x"]).id,
        "report_date": str(TODAY - timedelta(days=1)),
        **extra,
    }
    return client.post("/api/documents", json=body)


def act(client, doc, action, **body):
    return client.post(f"/api/documents/{doc['id']}/{action}", json={"version": doc["version"], **body})


def submitted(w, client=None):
    client = client or w["a"]
    r = create(client, w)
    assert r.status_code == 201, r.text
    doc = r.json()
    r = act(client, doc, "submit")
    assert r.status_code == 200, r.text
    return r.json()


# Isolation ------------------------------------------------------------------------------------


def test_another_supervisor_on_the_same_school_sees_nothing(w):
    doc = submitted(w)
    b = w["b"]
    assert b.get(f"/api/documents/{doc['id']}").status_code == 404
    assert b.get("/api/documents").json() == {"items": [], "total": 0, "page": 1}
    assert b.get("/api/documents", params={"q": doc["title"][:5]}).json()["total"] == 0
    dash = b.get("/api/documents/dashboard").json()
    assert sum(dash["counts"].values()) == 0 and dash["returned"] == [] and dash["access_history"] == []
    assert all(not s["covered"] for c in dash["coverage"] for s in c["schools"])
    assert b.post(f"/api/documents/{doc['id']}/link", json={}).status_code == 404
    assert b.get(f"/api/documents/{doc['id']}/access").status_code == 404
    with session_factory()() as db:
        denials = (
            db.execute(
                select(AuditLog).where(AuditLog.action == "permission.denied", AuditLog.entity_type == "document")
            )
            .scalars()
            .all()
        )
        assert denials and all(d.actor_id == w["user_b"].id for d in denials)


def test_reassignment_never_moves_documents(w):
    doc = submitted(w)
    head = w["head"]
    history = head.get("/api/assignments/history", params={"supervisor_id": w["sup_a"].id}).json()
    assignment = next(h for h in history if h["school"]["code"] == "SX")
    r = head.post(f"/api/assignments/{assignment['id']}/end", json={"version": assignment["version"], "reason": "x"})
    assert r.status_code == 200
    assert w["b"].get(f"/api/documents/{doc['id']}").status_code == 404
    assert w["a"].get(f"/api/documents/{doc['id']}").status_code == 200


def test_teachers_and_form_authors_see_nothing(w):
    doc = submitted(w)
    for client in (w["teacher_client"], w["author"]):
        assert client.get(f"/api/documents/{doc['id']}").status_code == 404
        assert client.get("/api/documents").json()["total"] == 0


def test_cluster_head_sees_only_forwarded_reports(w, new_client, outbox):
    doc = submitted(w)
    head, other = w["head"], w["other_head"]
    assert head.get(f"/api/documents/{doc['id']}").status_code == 404
    r = w["admin1"].post(f"/api/documents/{doc['id']}/forward", json={"note": "For your information"})
    assert r.status_code == 200, r.text
    assert head.get(f"/api/documents/{doc['id']}").status_code == 200
    assert [d["id"] for d in head.get("/api/documents").json()["items"]] == [doc["id"]]
    assert other.get(f"/api/documents/{doc['id']}").status_code == 404
    # FR-AS8: access follows the cluster's current Cluster Head.
    new_head_client, new_head = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head3@example.org", staff_id="CH3")
    with session_factory()() as db:
        db.get(Cluster, w["cluster"].id).cluster_head_id = new_head.id
        db.commit()
    assert new_head_client.get(f"/api/documents/{doc['id']}").status_code == 200
    assert head.get(f"/api/documents/{doc['id']}").status_code == 404
    w["admin1"].post(f"/api/documents/{doc['id']}/revoke-forward")
    assert new_head_client.get(f"/api/documents/{doc['id']}").status_code == 404


def test_only_admins_forward_and_only_to_the_cluster_head(w):
    doc = submitted(w)
    assert w["a"].post(f"/api/documents/{doc['id']}/forward", json={}).status_code == 403
    assert w["head"].post(f"/api/documents/{doc['id']}/forward", json={}).status_code == 403
    # The forward endpoint takes no recipient: it can only reach the document's cluster head.
    r = w["admin1"].post(f"/api/documents/{doc['id']}/forward", json={"note": "x", "user_id": w["user_b"].id})
    assert r.status_code == 200
    assert w["b"].get(f"/api/documents/{doc['id']}").status_code == 404


# Review ---------------------------------------------------------------------------------------


def test_admins_review_and_see_each_others_actions(w):
    doc = submitted(w)
    admin1, admin2 = w["admin1"], w["admin2"]
    assert [d["id"] for d in admin2.get("/api/documents").json()["items"]] == [doc["id"]]
    scan()
    opened = admin1.post(f"/api/documents/{doc['id']}/link", json={"disposition": "inline"})
    assert opened.status_code == 200
    viewed = admin2.get(f"/api/documents/{doc['id']}").json()
    assert viewed["status"] == "viewed" and viewed["first_viewed_by"] == "Mariam"
    r = act(admin2, viewed, "acknowledge", comment="Thank you")
    assert r.status_code == 200
    seen = admin1.get(f"/api/documents/{doc['id']}").json()
    assert seen["status"] == "acknowledged" and seen["acknowledged_by"] == "Huda"
    # The owner sees who opened it, and when.
    history = w["a"].get(f"/api/documents/{doc['id']}/access").json()
    assert history and history[0]["by"] == "Mariam" and history[0]["action"] == "viewed"


def test_return_and_resubmit(w):
    doc = submitted(w)
    r = act(w["admin1"], doc, "return", comment="Re-scan page 2; it is unreadable")
    assert r.status_code == 200
    a = w["a"]
    mine = a.get(f"/api/documents/{doc['id']}").json()
    assert mine["status"] == "returned" and mine["review_comment"].startswith("Re-scan")
    mine = a.post(
        f"/api/documents/{doc['id']}/versions", json={"version": mine["version"], "file_ids": [upload(a)]}
    ).json()
    assert [v["number"] for v in mine["versions"]] == [1, 2]
    assert act(a, mine, "submit").json()["status"] == "submitted"
    with session_factory()() as db:
        actions = [x.action for x in db.execute(select(AuditLog).where(AuditLog.entity_type == "document")).scalars()]
    assert actions.count("document.submitted") == 2 and "document.returned" in actions


def test_acknowledged_reports_are_locked_records(w):
    doc = submitted(w)
    doc = act(w["admin1"], doc, "acknowledge").json()
    a = w["a"]
    mine = a.get(f"/api/documents/{doc['id']}").json()
    assert act(a, mine, "withdraw").json()["error"]["code"] == "document_not_withdrawable"
    assert act(a, mine, "delete").json()["error"]["code"] == "document_not_deletable"
    no_reason = a.post(
        f"/api/documents/{doc['id']}/versions", json={"version": mine["version"], "file_ids": [upload(a)]}
    )
    assert no_reason.json()["error"]["code"] == "reason_required"
    fixed = a.post(
        f"/api/documents/{doc['id']}/versions",
        json={"version": mine["version"], "file_ids": [upload(a)], "reason": "Wrong page order"},
    )
    assert fixed.status_code == 200 and fixed.json()["status"] == "submitted"
    versions = w["admin1"].get(f"/api/documents/{doc['id']}").json()["versions"]
    assert [v["number"] for v in versions] == [1, 2]
    first = versions[0]["id"]
    scan()
    assert w["admin1"].post(f"/api/documents/{doc['id']}/link", json={"version_id": first}).status_code == 200


def test_withdraw_before_acknowledgement(w):
    doc = submitted(w)
    r = act(w["a"], doc, "withdraw")
    assert r.json()["status"] == "withdrawn"
    assert w["head"].get(f"/api/documents/{doc['id']}").status_code == 404


def test_soft_delete_and_restore(w):
    a = w["a"]
    doc = create(a, w).json()
    assert act(a, doc, "delete").status_code == 200
    assert a.get(f"/api/documents/{doc['id']}").status_code == 404
    assert a.get("/api/documents").json()["total"] == 0
    deleted = w["admin1"].get("/api/documents", params={"status": "deleted"}).json()["items"]
    assert [d["id"] for d in deleted] == [doc["id"]] and deleted[0]["status"] == "deleted"
    assert w["admin1"].post(f"/api/documents/{doc['id']}/restore").status_code == 200
    assert a.get(f"/api/documents/{doc['id']}").status_code == 200


# Upload rules -----------------------------------------------------------------------------------


def test_report_date_and_school_rules(w):
    a = w["a"]
    future = create(a, w, report_date=str(TODAY + timedelta(days=1)))
    assert future.json()["error"]["code"] == "report_date_in_future"
    before = create(a, w, report_date=str(TODAY - timedelta(days=90)))
    assert before.json()["error"]["code"] == "report_date_outside_assignment"
    other_cluster_school = make_school(w["other_cluster"], "SZ")
    assert create(a, w, school=other_cluster_school).status_code == 404


def test_teacher_reports_need_a_teacher_at_the_school(w):
    teacher_form = publish_direct(
        sample_schema(), TODAY - timedelta(days=1), TODAY + timedelta(days=9), code="MOE-TE-01", subject="teacher"
    )
    mrv = report_version_id(teacher_form)
    teacher = w["head"].post("/api/teachers", json=teacher_body(w["school_x"].id, email="fatima@example.org"))
    assert teacher.status_code == 201, teacher.text
    teacher = teacher.json()
    a = w["a"]
    missing = create(a, w, ministry_report_version_id=mrv)
    assert missing.json()["error"]["code"] == "teacher_required"
    ok = create(a, w, ministry_report_version_id=mrv, teacher_id=teacher["id"])
    assert ok.status_code == 201, ok.text


def test_unpublished_report_versions_cannot_be_used(w):
    with session_factory()() as db:
        form = db.get(FormVersion, w["form_id"])
        form.status = "in_review"
        db.commit()
    assert create(w["a"], w).json()["error"]["code"] == "report_version_unpublished"


def test_images_become_one_pdf_in_order(w):
    a = w["a"]
    pages = []
    for colour in ("red", "green", "blue"):
        out = io.BytesIO()
        Image.new("RGB", (120, 160), colour).save(out, "JPEG")
        pages.append(upload(a, out.getvalue(), f"{colour}.jpg"))
    r = a.post(
        "/api/documents",
        json={
            "file_ids": pages,
            "ministry_report_version_id": w["mrv"],
            "school_id": w["school_x"].id,
            "report_date": str(TODAY),
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["file"]["pages"] == 3
    # The parts are not kept twice.
    assert a.get(f"/api/files/{pages[0]}").status_code == 404


def test_retried_upload_creates_one_document(w):
    a = w["a"]
    body = {
        "ministry_report_version_id": w["mrv"],
        "school_id": w["school_x"].id,
        "report_date": str(TODAY),
        "client_key": "phone-1-0001",
    }
    ids = {a.post("/api/documents", json={**body, "file_ids": [upload(a)]}).json()["id"] for _ in range(3)}
    assert len(ids) == 1


def test_duplicate_file_warning(w):
    a = w["a"]
    content = pdf_bytes(1)
    first = a.post(
        "/api/documents",
        json={
            "file_ids": [upload(a, content)],
            "ministry_report_version_id": w["mrv"],
            "school_id": w["school_x"].id,
            "report_date": str(TODAY),
        },
    )
    assert first.status_code == 201
    body = {"ministry_report_version_id": w["mrv"], "school_id": w["school_x"].id, "report_date": str(TODAY)}
    again = a.post("/api/documents", json={**body, "file_ids": [upload(a, content)]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "duplicate_document"
    confirmed = a.post("/api/documents", json={**body, "file_ids": [upload(a, content)], "confirm_duplicate": True})
    assert confirmed.status_code == 201


# Serving ------------------------------------------------------------------------------------------


def test_watermark_for_everyone_but_the_owner(w):
    doc = submitted(w)
    scan()
    owner_copy = w["a"].get(w["a"].post(f"/api/documents/{doc['id']}/link", json={}).json()["url"]).content
    admin = w["admin1"]
    admin_copy = admin.get(admin.post(f"/api/documents/{doc['id']}/link", json={}).json()["url"]).content
    assert owner_copy != admin_copy
    with pikepdf.open(io.BytesIO(owner_copy)) as clean, pikepdf.open(io.BytesIO(admin_copy)) as marked:
        assert len(clean.pages) == len(marked.pages) == 2
        for page in marked.pages:
            assert any(
                "SCES" in str(f.get("/BaseFont"))
                for x in page.Resources.XObject.values()
                for f in x.get("/Resources", {}).get("/Font", {}).values()
            )
    # The stored original is unchanged.
    with session_factory()() as db:
        from app.models import DocumentVersion, StoredFile

        version = db.execute(select(DocumentVersion)).scalar_one()
        stored = files.read_content(db.get(StoredFile, version.stored_file_id))
    assert stored == owner_copy


def test_admin_link_does_not_work_in_another_session(w):
    doc = submitted(w)
    scan()
    url = w["admin1"].post(f"/api/documents/{doc['id']}/link", json={}).json()["url"]
    # Another admin's session, and the owner's, cannot use the link.
    assert w["admin2"].get(url).status_code == 404
    assert w["a"].get(url).status_code == 404


# Dashboard ------------------------------------------------------------------------------------------


def test_supervisor_dashboard(w):
    a = w["a"]
    doc = submitted(w)
    draft = create(a, w, school=w["school_y"])
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "draft"
    act(w["admin1"], doc, "return", comment="Missing signature")
    dash = a.get("/api/documents/dashboard").json()
    assert dash["counts"]["returned"] == 1 and dash["counts"]["draft"] == 1
    assert dash["returned"][0]["review_comment"] == "Missing signature"
    coverage = dash["coverage"][0]["schools"]
    # A returned report does not count as covered; neither does a draft.
    assert {s["code"]: s["covered"] for s in coverage} == {"SX": False, "SY": False}
    mine = a.get(f"/api/documents/{doc['id']}").json()
    act(a, mine, "submit")
    coverage = a.get("/api/documents/dashboard").json()["coverage"][0]["schools"]
    assert {s["code"]: s["covered"] for s in coverage} == {"SX": True, "SY": False}


def test_admin_inbox_filters_and_order(w):
    first = submitted(w)
    second = create(w["a"], w, school=w["school_y"]).json()
    second = act(w["a"], second, "submit").json()
    act(w["admin1"], first, "acknowledge")
    inbox = w["admin1"].get("/api/documents").json()["items"]
    # Unacknowledged work comes first.
    assert [d["id"] for d in inbox] == [second["id"], first["id"]]
    only_y = w["admin1"].get("/api/documents", params={"school_id": w["school_y"].id}).json()["items"]
    assert [d["id"] for d in only_y] == [second["id"]]
    by_code = w["admin1"].get("/api/documents", params={"report_code": "MOE-SV-01"}).json()
    assert by_code["total"] == 2


def test_notifications_follow_the_review(w):
    doc = submitted(w)
    act(w["admin1"], doc, "return", comment="Unreadable")
    with session_factory()() as db:
        from app.models import Notification

        types = [(n.user_id, n.type) for n in db.execute(select(Notification)).scalars()]
    assert (w["user_a"].id, "report_returned") in types
    assert sum(1 for _, t in types if t == "report_submitted") == 2  # both admins
