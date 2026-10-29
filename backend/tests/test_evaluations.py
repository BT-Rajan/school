import io
from datetime import datetime, timedelta

import pikepdf
import pytest
from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.files import service as files
from app.models import AuditLog, Evaluation, EvaluationAmendment, MfaMethod, Notification, Role

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


@pytest.fixture
def world(new_client, outbox):
    # 10/11/2026, 09:00 in Kuwait.
    clock.freeze(datetime(2026, 11, 10, 6, 0))
    seed_reference()
    head, head_user = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head@example.org", staff_id="CH")
    other_head, other_user = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head2@example.org", staff_id="CH2")
    admin, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    cluster, other_cluster = make_cluster("C1", head_user), make_cluster("C2", other_user)
    school, school2 = make_school(cluster, "S1"), make_school(cluster, "S2")
    sup_a, _ = make_supervisor(cluster, "a@example.org", "SA")
    sup_b, _ = make_supervisor(cluster, "b@example.org", "SB")
    assign_direct(sup_a.id, school.id, TODAY - timedelta(days=30))
    assign_direct(sup_b.id, school.id, TODAY - timedelta(days=30))
    form_id = publish_direct(sample_schema(), TODAY - timedelta(days=5), TODAY + timedelta(days=20))
    a, b = new_client(), new_client()
    login(a, outbox, "a@example.org")
    login(b, outbox, "b@example.org")
    return locals()


GOOD = {
    "met_principal": True,
    "classrooms": 6,
    "rating": 4,
    "areas": ["safety", "teaching"],
    "staff": [{"name": "Ali", "present": True}],
    "notes": "ملاحظات الزيارة",
}


def start(client, w, **extra):
    return client.post("/api/evaluations", json={"form_id": w["form_id"], "school_id": w["school"].id, **extra})


def save(client, e, **body):
    return client.patch(f"/api/evaluations/{e['id']}", json={"version": e["version"], **body})


def submit(client, e, **body):
    return client.post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"], **body})


def test_full_lifecycle(world):
    a = world["a"]
    e = start(a, world, visit_date=str(TODAY))
    assert e.status_code == 201, e.text
    e = e.json()
    assert e["status"] == "draft" and [s["key"] for s in e["sections"]] == ["visit"]
    # Drafts may be partial but must be well typed.
    bad = save(a, e, sections={"visit": {"classrooms": "six"}})
    assert bad.json()["error"]["code"] == "answers_invalid"
    e = save(a, e, sections={"visit": {"classrooms": 6}}).json()
    # Submitting with required answers missing is refused.
    r = submit(a, e)
    assert r.status_code == 422 and {"where": "visit.met_principal", "code": "required"} in r.json()["error"]["detail"]
    e = save(a, e, sections={"visit": GOOD}, visit_notes="Good visit").json()
    r = submit(a, e, location={"latitude": 29.33, "longitude": 48.0, "accuracy_m": 15})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["status"] == "submitted" and e["location"]["accuracy_m"] == 15
    # Submitted content is locked.
    assert save(a, e, sections={"visit": GOOD}).json()["error"]["code"] == "evaluation_locked"
    # Corrections are amendments that keep the prior answers.
    changed = {**GOOD, "classrooms": 7}
    r = a.post(
        f"/api/evaluations/{e['id']}/amend",
        json={"version": e["version"], "reason": "Miscounted", "sections": {"visit": changed}},
    )
    assert r.status_code == 200 and r.json()["status"] == "amended"
    history = a.get(f"/api/evaluations/{e['id']}/amendments").json()
    assert history[0]["reason"] == "Miscounted" and history[0]["prior"]["sections"]["visit"]["classrooms"] == 6
    with session_factory()() as db:
        assert db.execute(select(AuditLog).where(AuditLog.action == "evaluation.amended")).scalar_one()


def test_visit_date_must_be_in_assignment_window(world):
    a = world["a"]
    r = start(a, world, visit_date=str(TODAY - timedelta(days=60)))
    assert r.json()["error"]["code"] == "visit_date_outside_assignment"
    r = start(a, world, visit_date=str(TODAY + timedelta(days=1)))
    assert r.json()["error"]["code"] == "visit_date_in_future"
    e = start(a, world).json()
    assert submit(a, save(a, e, sections={"visit": GOOD}).json()).json()["error"]["detail"] == [
        {"where": "visit_date", "code": "required"}
    ]


def test_only_assigned_schools_and_active_forms(world):
    a = world["a"]
    r = a.post("/api/evaluations", json={"form_id": world["form_id"], "school_id": world["school2"].id})
    assert r.status_code == 404
    later = publish_direct(sample_schema(), TODAY + timedelta(days=3), TODAY + timedelta(days=9), version="2026.2")
    r = a.post("/api/evaluations", json={"form_id": later, "school_id": world["school"].id})
    assert r.json()["error"]["code"] == "form_not_active"
    # Only supervisors start evaluations.
    assert start(world["head"], world).status_code == 403


def test_teacher_evaluation_needs_a_teacher_at_the_school(world):
    form = publish_direct(sample_schema(), TODAY, TODAY + timedelta(days=9), code="MOE-TE-01", subject="teacher")
    teacher = world["head"].post("/api/teachers", json=teacher_body(world["school"].id)).json()
    other = (
        world["head"]
        .post("/api/teachers", json=teacher_body(world["school2"].id, staff_id="T-2", email="t2@example.org"))
        .json()
    )
    a = world["a"]
    bad = a.post("/api/evaluations", json={"form_id": form, "school_id": world["school"].id, "teacher_id": other["id"]})
    assert bad.json()["error"]["code"] == "teacher_not_at_school"
    ok = a.post(
        "/api/evaluations", json={"form_id": form, "school_id": world["school"].id, "teacher_id": teacher["id"]}
    )
    assert ok.status_code == 201 and ok.json()["teacher"]["name"] == "Fatima Al-Sabah"


def test_supervisors_cannot_see_each_others_evaluations(world):
    e = start(world["a"], world).json()
    assert world["b"].get(f"/api/evaluations/{e['id']}").status_code == 404
    assert world["b"].get("/api/evaluations").json()["items"] == []
    assert world["head"].get(f"/api/evaluations/{e['id']}").status_code == 200
    assert world["other_head"].get(f"/api/evaluations/{e['id']}").status_code == 404
    assert world["admin"].get(f"/api/evaluations/{e['id']}").status_code == 200
    assert save(world["b"], e, sections={"visit": GOOD}).status_code == 404
    with session_factory()() as db:
        denied = db.execute(select(AuditLog).where(AuditLog.action == "permission.denied")).scalars().all()
        assert any(d.entity_type == "evaluation" for d in denied)


def test_unassign_requires_a_choice_for_drafts(world):
    head = world["head"]
    e = start(world["a"], world).json()
    history = head.get("/api/assignments/history", params={"supervisor_id": world["sup_a"].id}).json()
    assignment = history[0]
    r = head.post(f"/api/assignments/{assignment['id']}/end", json={"version": assignment["version"], "reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["detail"] == {"count": 1}
    r = head.post(
        f"/api/assignments/{assignment['id']}/end",
        json={
            "version": assignment["version"],
            "reason": "Moved",
            "drafts": "transfer",
            "transfer_to_supervisor_id": world["sup_b"].id,
        },
    )
    assert r.status_code == 200, r.text
    # The draft now belongs to supervisor B.
    assert world["b"].get(f"/api/evaluations/{e['id']}").status_code == 200
    assert world["a"].get(f"/api/evaluations/{e['id']}").status_code == 404


def test_submission_closes_with_the_form(world, outbox):
    a = world["a"]
    e = save(a, start(a, world, visit_date=str(TODAY)).json(), sections={"visit": GOOD}).json()
    clock.freeze(datetime(2026, 12, 1, 6, 0))  # after the end date, 30/11/2026
    login(a, outbox, "a@example.org")
    assert submit(a, e).json()["error"]["code"] == "form_closed"


def test_cancel_draft(world):
    a = world["a"]
    e = start(a, world).json()
    r = a.post(f"/api/evaluations/{e['id']}/cancel", json={"version": e["version"], "reason": "Duplicate"})
    assert r.json()["status"] == "cancelled"


def test_client_key_is_idempotent(world):
    a = world["a"]
    first = start(a, world, client_key="device-1-abc").json()
    again = start(a, world, client_key="device-1-abc").json()
    assert first["id"] == again["id"]
    with session_factory()() as db:
        assert len(db.execute(select(Evaluation)).scalars().all()) == 1


def test_file_answers_must_be_your_own_uploads(world):
    schema = sample_schema()
    schema["sections"][0]["questions"].append(
        {"key": "evidence", "type": "file", "label": {"en": "Evidence", "ar": "الأدلة"}, "max_files": 2}
    )
    form = publish_direct(schema, TODAY, TODAY + timedelta(days=5), version="2026.3")
    a, b = world["a"], world["b"]
    mine = a.post("/api/files", files={"file": ("a.pdf", pdf_bytes())}).json()
    theirs = b.post("/api/files", files={"file": ("b.pdf", pdf_bytes())}).json()
    e = a.post("/api/evaluations", json={"form_id": form, "school_id": world["school"].id}).json()
    bad = save(a, e, sections={"visit": {"evidence": [theirs["id"]]}})
    assert bad.json()["error"]["detail"] == [{"where": "visit.evidence", "code": "file_not_usable"}]
    ok = save(a, e, sections={"visit": {"evidence": [mine["id"]]}})
    assert ok.status_code == 200
    # The file now belongs to the evaluation: the Cluster Head can open it, the other supervisor cannot.
    with session_factory()() as db:
        files.scan_pending(db)
    assert world["head"].get(f"/api/files/{mine['id']}").status_code == 200
    assert b.get(f"/api/files/{mine['id']}").status_code == 404


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_pdf_report(world, locale):
    a = world["a"]
    e = save(a, start(a, world, visit_date=str(TODAY)).json(), sections={"visit": GOOD}).json()
    assert a.get(f"/api/evaluations/{e['id']}/pdf").json()["error"]["code"] == "evaluation_not_submitted"
    e = submit(a, e).json()
    r = a.get(f"/api/evaluations/{e['id']}/pdf", params={"locale": locale})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "MOE-SV-01-2026.1" in r.headers["content-disposition"]
    with pikepdf.open(io.BytesIO(r.content)) as pdf:
        assert len(pdf.pages) >= 1
        fonts = {str(f.get("/BaseFont")) for page in pdf.pages for f in page.Resources.Font.values()}
        assert any("SCES" in name for name in fonts)
    # Cluster Heads can download it too; the other supervisor cannot.
    assert world["head"].get(f"/api/evaluations/{e['id']}/pdf").status_code == 200
    assert world["b"].get(f"/api/evaluations/{e['id']}/pdf").status_code == 404


def test_amendment_rejected_for_drafts(world):
    a = world["a"]
    e = start(a, world).json()
    r = a.post(f"/api/evaluations/{e['id']}/amend", json={"version": e["version"], "reason": "x", "sections": {}})
    assert r.json()["error"]["code"] == "evaluation_not_submitted"
    with session_factory()() as db:
        assert not db.execute(select(EvaluationAmendment)).first()


def notices(type_: str) -> list[tuple[int, dict]]:
    with session_factory()() as db:
        rows = db.execute(select(Notification).where(Notification.type == type_)).scalars()
        return [(n.user_id, n.payload) for n in rows]


def test_reviewers_hear_about_submissions_and_amendments(world):
    a = world["a"]
    e = save(a, start(a, world, visit_date=str(TODAY)).json(), sections={"visit": GOOD}).json()
    e = submit(a, e).json()
    submitted = notices("evaluation_submitted")
    # The admin and this cluster's head; not the other cluster's head.
    recipients = {user_id for user_id, _ in submitted}
    assert world["head_user"].id in recipients and world["other_user"].id not in recipients
    assert len(recipients) == 2
    assert submitted[0][1]["school"] == world["school"].name
    a.post(
        f"/api/evaluations/{e['id']}/amend",
        json={"version": e["version"], "reason": "Miscounted", "sections": {"visit": GOOD}},
    )
    assert {p["reason"] for _, p in notices("evaluation_amended")} == {"Miscounted"}


def test_transferred_drafts_are_announced(world):
    start(world["a"], world)
    head = world["head"]
    assignment = head.get("/api/assignments/history", params={"supervisor_id": world["sup_a"].id}).json()[0]
    head.post(
        f"/api/assignments/{assignment['id']}/end",
        json={
            "version": assignment["version"],
            "reason": "Moved",
            "drafts": "transfer",
            "transfer_to_supervisor_id": world["sup_b"].id,
        },
    )
    [(user_id, payload)] = notices("evaluations_transferred")
    assert user_id == world["sup_b"].user_id and payload["count"] == 1
