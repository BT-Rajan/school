"""Teacher requests (section 8.6) and teacher sections of evaluations (FR-E2, FR-E3, FR-E6, FR-S6, 6.1)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.models import AuditLog, MailMessage, MailStatus, MfaMethod, Notification, Role
from app.requests import service as requests

from .helpers import (
    assign_direct,
    login,
    make_cluster,
    make_school,
    make_supervisor,
    make_teacher,
    publish_direct,
    sample_schema,
    signed_in,
)

TODAY = datetime(2026, 11, 10).date()
SUPERVISOR_ANSWERS = {
    "met_principal": True,
    "classrooms": 6,
    "rating": 4,
    "areas": ["safety"],
    "staff": [{"name": "Ali", "present": True}],
}


@pytest.fixture
def world(new_client, outbox):
    clock.freeze(datetime(2026, 11, 10, 6, 0))  # 10/11/2026, 09:00 in Kuwait
    head, head_user = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head@example.org", staff_id="CH")
    other_head, other_head_user = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head2@example.org", staff_id="CH2")
    admin, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    cluster, other_cluster = make_cluster("C1", head_user), make_cluster("C2", other_head_user)
    s1, s2 = make_school(cluster, "S1"), make_school(cluster, "S2")
    far = make_school(other_cluster, "S9")
    sup_a, user_a = make_supervisor(cluster, "a@example.org", "SA")
    sup_b, user_b = make_supervisor(cluster, "b@example.org", "SB")
    for s in (sup_a, sup_b):
        assign_direct(s.id, s1.id, TODAY - timedelta(days=30))
    assign_direct(sup_a.id, s2.id, TODAY - timedelta(days=30))
    school_form = publish_direct(
        sample_schema(teacher_section=True), TODAY - timedelta(days=5), TODAY + timedelta(days=20)
    )
    teacher_form = publish_direct(
        sample_schema(teacher_section=True),
        TODAY - timedelta(days=5),
        TODAY + timedelta(days=20),
        code="MOE-TV-01",
        subject="teacher",
    )
    teachers = {}
    clients = {}
    for key, school, staff in (("t1", s1, "T1"), ("t2", s1, "T2"), ("t3", s2, "T3"), ("t9", far, "T9")):
        teacher, user, secret = make_teacher(school, f"{key}@example.org", staff, name=f"Teacher {key}")
        teachers[key] = teacher
        clients[key] = new_client()
        login(clients[key], outbox, f"{key}@example.org", secret=secret)
    a, b = new_client(), new_client()
    login(a, outbox, "a@example.org")
    login(b, outbox, "b@example.org")
    return dict(locals())


def contact(w, school, teacher):
    r = w["head"].put(f"/api/schools/{school.id}/contact", json={"teacher_id": teacher.id})
    assert r.status_code == 200, r.text


def start(w, client=None, form=None, school=None, teacher=None):
    body = {"form_id": form or w["school_form"], "school_id": (school or w["s1"]).id, "visit_date": str(TODAY)}
    if teacher is not None:
        body["teacher_id"] = teacher.id
    r = (client or w["a"]).post("/api/evaluations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def fill(w, e):
    r = w["a"].patch(
        f"/api/evaluations/{e['id']}", json={"version": e["version"], "sections": {"visit": SUPERVISOR_ANSWERS}}
    )
    assert r.status_code == 200, r.text
    return r.json()


def get(client, request_id):
    return client.get(f"/api/requests/{request_id}").json()


def actions(request_id):
    with session_factory()() as db:
        return [
            a.action
            for a in db.execute(
                select(AuditLog).where(AuditLog.entity_type == "request", AuditLog.entity_id == str(request_id))
            ).scalars()
            if a.action.startswith("request.")
        ]


def test_school_evaluation_goes_to_the_contact_teacher(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    e = start(w)
    request = e["request"]
    assert request["teacher"]["id"] == w["teachers"]["t1"].id and request["status"] == "not_started"
    # Default due date: a week, within the form's window.
    assert request["due_date"] == str(TODAY + timedelta(days=7))
    t1 = w["clients"]["t1"]
    listed = t1.get("/api/requests").json()["items"]
    assert [r["id"] for r in listed] == [request["id"]]
    detail = get(t1, request["id"])
    # The teacher sees only the teacher sections, never the supervisor's (FR-E10).
    assert [s["key"] for s in detail["sections"]] == ["self"]
    assert detail["can"]["answer"] is True
    assert t1.get(f"/api/evaluations/{e['id']}").status_code == 404
    for other in ("t2", "t3", "t9"):
        assert w["clients"][other].get(f"/api/requests/{request['id']}").status_code == 404
        assert w["clients"][other].get("/api/requests").json()["items"] == []
    with session_factory()() as db:
        assert db.execute(select(Notification).where(Notification.type == "request_assigned")).scalar_one()


def test_answer_return_resubmit_and_submit_the_evaluation(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    e = fill(w, start(w))
    request_id = e["request"]["id"]
    # FR-E6: the evaluation waits for the teacher.
    r = w["a"].post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "teacher_section_pending"
    t1 = w["clients"]["t1"]
    req = get(t1, request_id)
    req = t1.patch(
        f"/api/requests/{request_id}", json={"version": req["version"], "sections": {"self": {"comment": "مسودة"}}}
    ).json()
    assert req["status"] == "in_progress"
    req = t1.post(
        f"/api/requests/{request_id}/submit",
        json={"version": req["version"], "sections": {"self": {"comment": "Done"}}},
    ).json()
    assert req["status"] == "submitted"
    # Submitted answers are locked.
    r = t1.patch(
        f"/api/requests/{request_id}", json={"version": req["version"], "sections": {"self": {"comment": "x"}}}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "request_locked"
    # The requester returns it with a comment; the teacher sees why and resubmits.
    req = get(w["a"], request_id)
    assert req["can"]["manage"] is True and req["answers"] == {"self": {"comment": "Done"}}
    req = (
        w["a"]
        .post(f"/api/requests/{request_id}/return", json={"version": req["version"], "comment": "Add detail"})
        .json()
    )
    assert req["status"] == "returned"
    seen = get(t1, request_id)
    assert seen["return_comment"] == "Add detail" and seen["can"]["answer"] is True
    t1.post(
        f"/api/requests/{request_id}/submit",
        json={"version": seen["version"], "sections": {"self": {"comment": "More detail"}}},
    )
    # Only the requester returns, and other supervisors of the school see nothing.
    req = get(w["a"], request_id)
    assert w["b"].get(f"/api/requests/{request_id}").status_code == 404
    assert (
        t1.post(f"/api/requests/{request_id}/return", json={"version": req["version"], "comment": "x"}).status_code
        == 403
    )
    e = w["a"].get(f"/api/evaluations/{e['id']}").json()
    r = w["a"].post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"]})
    assert r.status_code == 200, r.text
    teacher_section = next(s for s in r.json()["sections"] if s["respondent"] == "teacher")
    assert teacher_section["answers"] == {"comment": "More detail"}
    # Once the evaluation is submitted the request cannot be returned again.
    req = get(w["a"], request_id)
    assert (
        w["a"].post(f"/api/requests/{request_id}/return", json={"version": req["version"], "comment": "x"}).status_code
        == 409
    )
    assert w["a"].get(f"/api/evaluations/{e['id']}/pdf?locale=ar").status_code == 200
    # FR-R5: every step is audited.
    assert actions(request_id) == [
        "request.created",
        "request.saved",
        "request.submitted",
        "request.returned",
        "request.resubmitted",
    ]


def test_required_teacher_answers_are_checked(world):
    w = world
    schema = sample_schema(teacher_section=True)
    schema["sections"][1]["questions"][0]["required"] = True
    form = publish_direct(schema, TODAY, TODAY + timedelta(days=10), code="REQ-1")
    contact(w, w["s1"], w["teachers"]["t1"])
    request_id = start(w, form=form)["request"]["id"]
    t1 = w["clients"]["t1"]
    req = get(t1, request_id)
    r = t1.post(f"/api/requests/{request_id}/submit", json={"version": req["version"], "sections": {}})
    assert r.status_code == 422 and {"where": "self.comment", "code": "required"} in r.json()["error"]["detail"]
    r = t1.patch(f"/api/requests/{request_id}", json={"version": req["version"], "sections": {"visit": {"rating": 1}}})
    assert r.json()["error"]["detail"] == [{"where": "visit", "code": "section_not_yours"}]


def test_waiver_by_the_cluster_head(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    e = fill(w, start(w))
    request_id = e["request"]["id"]
    req = get(w["a"], request_id)
    body = {"version": req["version"], "reason": "Teacher on leave"}
    assert w["a"].post(f"/api/requests/{request_id}/waive", json=body).status_code == 403
    assert w["other_head"].post(f"/api/requests/{request_id}/waive", json=body).status_code == 404
    r = w["head"].post(f"/api/requests/{request_id}/waive", json=body)
    assert r.status_code == 200 and r.json()["status"] == "waived"
    e = w["a"].get(f"/api/evaluations/{e['id']}").json()
    assert w["a"].post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"]}).status_code == 200


def test_no_contact_teacher_then_one_is_named(world):
    w = world
    e = start(w)
    request_id = e["request"]["id"]
    assert e["request"]["teacher"] is None
    assert [r["id"] for r in w["a"].get("/api/requests", params={"show": "unaddressed"}).json()["items"]] == [
        request_id
    ]
    contact(w, w["s1"], w["teachers"]["t2"])
    assert get(w["clients"]["t2"], request_id)["teacher"]["id"] == w["teachers"]["t2"].id
    with session_factory()() as db:
        types = {n.type for n in db.execute(select(Notification)).scalars()}
    assert {"request_assigned", "request_moved"} <= types


def test_contact_change_moves_unstarted_requests_and_asks_about_started_ones(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    fresh = start(w)["request"]["id"]
    started = start(w)["request"]["id"]
    t1 = w["clients"]["t1"]
    req = get(t1, started)
    t1.patch(f"/api/requests/{started}", json={"version": req["version"], "sections": {"self": {"comment": "half"}}})
    contact(w, w["s1"], w["teachers"]["t2"])
    # Not started: moves at once.
    assert get(w["clients"]["t2"], fresh)["status"] == "not_started"
    assert w["clients"]["t1"].get(f"/api/requests/{fresh}").status_code == 404
    # Started: stays until the requester confirms.
    req = get(w["a"], started)
    assert req["teacher"]["id"] == w["teachers"]["t1"].id and req["pending_teacher"]["id"] == w["teachers"]["t2"].id
    assert [r["id"] for r in w["a"].get("/api/requests", params={"show": "awaiting_confirmation"}).json()["items"]] == [
        started
    ]
    r = w["a"].post(f"/api/requests/{started}/confirm-move", json={"version": req["version"], "accept": True})
    assert r.status_code == 200 and r.json()["teacher"]["id"] == w["teachers"]["t2"].id
    assert get(w["clients"]["t2"], started)["answers"] == {"self": {"comment": "half"}}
    assert w["clients"]["t1"].get(f"/api/requests/{started}").status_code == 404


def test_declining_a_move_keeps_the_teacher(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    started = start(w)["request"]["id"]
    t1 = w["clients"]["t1"]
    req = get(t1, started)
    t1.patch(f"/api/requests/{started}", json={"version": req["version"], "sections": {"self": {"comment": "mine"}}})
    contact(w, w["s1"], w["teachers"]["t2"])
    req = get(w["a"], started)
    r = w["a"].post(f"/api/requests/{started}/confirm-move", json={"version": req["version"], "accept": False})
    assert r.json()["teacher"]["id"] == w["teachers"]["t1"].id and r.json()["pending_teacher"] is None


def test_teacher_evaluation_request_stays_with_a_transferred_teacher(world):
    w = world
    t2 = w["teachers"]["t2"]
    e = start(w, form=w["teacher_form"], teacher=t2)
    request_id = e["request"]["id"]
    assert e["request"]["teacher"]["id"] == t2.id
    r = w["head"].post(f"/api/teachers/{t2.id}/transfer", json={"school_id": w["s2"].id})
    assert r.status_code == 200, r.text
    # Section 6.1: the request stays with the teacher, and the requester keeps their view.
    client = w["clients"]["t2"]
    req = get(client, request_id)
    assert req["can"]["answer"] is True
    assert (
        client.post(
            f"/api/requests/{request_id}/submit",
            json={"version": req["version"], "sections": {"self": {"comment": "ok"}}},
        ).status_code
        == 200
    )
    assert get(w["a"], request_id)["status"] == "submitted"


def test_cancelled_evaluation_cancels_its_request(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    e = start(w)
    request_id = e["request"]["id"]
    w["a"].post(f"/api/evaluations/{e['id']}/cancel", json={"version": e["version"], "reason": "Wrong school"})
    req = get(w["clients"]["t1"], request_id)
    assert req["status"] == "cancelled" and req["can"]["answer"] is False
    r = w["clients"]["t1"].patch(f"/api/requests/{request_id}", json={"version": req["version"], "sections": {}})
    assert r.status_code == 409


def test_draft_transfer_hands_over_the_request(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    e = start(w)
    request_id = e["request"]["id"]
    assignment = w["head"].get("/api/assignments/history", params={"supervisor_id": w["sup_a"].id}).json()
    s1_assignment = next(a for a in assignment if a["school"]["id"] == w["s1"].id)
    r = w["head"].post(
        f"/api/assignments/{s1_assignment['id']}/end",
        json={
            "version": s1_assignment["version"],
            "reason": "Moved",
            "drafts": "transfer",
            "transfer_to_supervisor_id": w["sup_b"].id,
        },
    )
    assert r.status_code == 200, r.text
    assert get(w["b"], request_id)["can"]["manage"] is True


def test_standalone_requests(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    body = {"form_id": w["school_form"], "due_date": str(TODAY + timedelta(days=5)), "school_ids": [w["s1"].id]}
    r = w["head"].post("/api/requests", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "form_not_for_requests"
    catalog = w["admin"].get("/api/catalog").json()
    report_id = next(c["id"] for c in catalog if c["report_code"] == "MOE-SV-01")
    assert w["head"].post(f"/api/catalog/reports/{report_id}/standalone", json={"allowed": True}).status_code == 403
    assert w["admin"].post(f"/api/catalog/reports/{report_id}/standalone", json={"allowed": True}).status_code == 200
    # A Cluster Head asks a school's contact teacher and a named teacher.
    created = w["head"].post(
        "/api/requests", json={**body, "teacher_ids": [w["teachers"]["t2"].id], "instructions": "Update the profile"}
    )
    assert created.status_code == 201, created.text
    by_teacher = {r["teacher"]["id"]: r for r in created.json()}
    assert set(by_teacher) == {w["teachers"]["t1"].id, w["teachers"]["t2"].id}
    assert by_teacher[w["teachers"]["t1"].id]["via_contact"] is True
    # Out of scope: another cluster's head, and a supervisor for a school not assigned to them.
    assert w["other_head"].post("/api/requests", json=body).status_code == 404
    far = {**body, "school_ids": [], "teacher_ids": [w["teachers"]["t9"].id]}
    assert w["a"].post("/api/requests", json=far).status_code == 404
    assert w["clients"]["t1"].post("/api/requests", json=body).status_code == 403
    # The teacher answers; the requester can cancel open ones.
    one = by_teacher[w["teachers"]["t2"].id]
    detail = get(w["clients"]["t2"], one["id"])
    assert detail["instructions"] == "Update the profile"
    other = by_teacher[w["teachers"]["t1"].id]
    r = w["head"].post(
        f"/api/requests/{other['id']}/cancel", json={"version": other["version"], "reason": "Not needed"}
    )
    assert r.json()["status"] == "cancelled"


def test_reminders_before_on_and_after_the_due_date(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    request_id = start(w)["request"]["id"]
    due = TODAY + timedelta(days=7)

    def run_on(day):
        clock.freeze(datetime(day.year, day.month, day.day, 6, 0))
        with session_factory()() as db:
            return requests.remind(db)

    def notices(type_):
        with session_factory()() as db:
            return db.execute(select(Notification).where(Notification.type == type_)).scalars().all()

    assert run_on(due - timedelta(days=4)) == 0
    assert run_on(due - timedelta(days=3)) == 1
    assert run_on(due - timedelta(days=2)) == 0  # never twice
    assert run_on(due) == 1
    assert run_on(due + timedelta(days=1)) == 1
    assert run_on(due + timedelta(days=2)) == 0
    assert len(notices("request_due_soon")) == len(notices("request_due_today")) == len(notices("request_overdue")) == 1
    [requester_notice] = notices("request_overdue_requester")
    assert requester_notice.user_id == w["user_a"].id
    # The jump of several days ended the browser sessions, so read the request directly.
    with session_factory()() as db:
        from app.models import TeacherRequest

        assert requests.is_overdue(db, db.get(TeacherRequest, request_id))
    # Reminder emails wait for the daily digest, so sign-in codes are never queued behind them.
    with session_factory()() as db:
        statuses = {m.status for m in db.execute(select(MailMessage).where(MailMessage.template == "notice")).scalars()}
    assert statuses == {MailStatus.DIGEST_PENDING}


def test_new_due_date_and_instructions(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    request_id = start(w)["request"]["id"]
    req = get(w["a"], request_id)
    r = w["a"].post(
        f"/api/requests/{request_id}/settings",
        json={"version": req["version"], "due_date": str(TODAY - timedelta(days=1))},
    )
    assert r.status_code == 422
    r = w["a"].post(
        f"/api/requests/{request_id}/settings",
        json={"version": req["version"], "due_date": str(TODAY + timedelta(days=2)), "instructions": "Please be brief"},
    )
    assert r.status_code == 200 and r.json()["instructions"] == "Please be brief"
    assert (
        w["clients"]["t1"]
        .post(f"/api/requests/{request_id}/settings", json={"version": r.json()["version"], "due_date": str(TODAY)})
        .status_code
        == 403
    )


def test_request_history_is_for_staff(world):
    w = world
    contact(w, w["s1"], w["teachers"]["t1"])
    request_id = start(w)["request"]["id"]
    assert [h["action"] for h in w["a"].get(f"/api/requests/{request_id}/history").json()] == ["created"]
    assert w["clients"]["t1"].get(f"/api/requests/{request_id}/history").status_code == 403


def test_teachers_are_invited_in_bulk_within_the_daily_cap(world, outbox):
    from app.models import District, User, UserStatus

    w = world
    with session_factory()() as db:
        district = db.execute(select(District)).scalar_one()
        district.settings = {**district.settings, "invitation_daily_cap": 2}
        for key in ("t1", "t2", "t3"):
            db.get(User, db.get(type(w["teachers"][key]), w["teachers"][key].id).user_id).status = UserStatus.INVITED
        db.commit()
    assert w["head"].get("/api/teachers/onboarding").json() == {"active": 0, "invited": 0, "needs_invitation": 3}
    # Another cluster's teacher is not the head's to invite.
    r = w["head"].post("/api/teachers/invitations", json={})
    assert r.status_code == 200
    assert r.json() == {
        "queued": 3,
        "by_day": [{"date": str(TODAY), "count": 2}, {"date": str(TODAY + timedelta(days=1)), "count": 1}],
    }
    assert w["head"].get("/api/teachers/onboarding").json()["invited"] == 3
    # Running it again queues nothing: live invitations are left alone.
    assert w["head"].post("/api/teachers/invitations", json={}).json()["queued"] == 0
    assert w["other_head"].post("/api/teachers/invitations", json={"cluster_id": w["cluster"].id}).status_code == 404
    assert w["clients"]["t9"].post("/api/teachers/invitations", json={}).status_code == 403
