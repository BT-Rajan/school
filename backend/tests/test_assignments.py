import threading
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.mail import queue
from app.models import MfaMethod, Notification, Role, Supervisor

from .helpers import (
    deliver_mail,
    login,
    make_cluster,
    make_school,
    make_user,
    seed_reference,
    signed_in,
    teacher_body,
)


def make_supervisor(cluster, email: str, staff_id: str):
    user, _ = make_user(Role.SUPERVISOR, email, staff_id=staff_id)
    with session_factory()() as db:
        s = Supervisor(user_id=user.id, cluster_id=cluster.id)
        db.add(s)
        db.commit()
        db.refresh(s)
        return s, user


@pytest.fixture
def world(new_client, outbox):
    seed_reference()
    head_client, head = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head@example.org", staff_id="CH")
    other_head_client, other_head = signed_in(
        new_client, outbox, Role.CLUSTER_HEAD, "head2@example.org", staff_id="CH2"
    )
    cluster = make_cluster("C1", head)
    other_cluster = make_cluster("C2", other_head)
    school = make_school(cluster, "S1")
    school2 = make_school(cluster, "S2")
    far_school = make_school(other_cluster, "S9")
    sup_a, user_a = make_supervisor(cluster, "a@example.org", "SA")
    sup_b, user_b = make_supervisor(cluster, "b@example.org", "SB")
    sup_far, _ = make_supervisor(other_cluster, "far@example.org", "SF")
    return locals()


def today():
    return clock.local_date("Asia/Kuwait")


def assign(client, supervisor_id, school_id, **extra):
    return client.post("/api/assignments", json={"supervisor_id": supervisor_id, "school_id": school_id, **extra})


def test_assign_and_reject_overlap(world):
    c = world["head_client"]
    r = assign(c, world["sup_a"].id, world["school"].id)
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "active"
    dup = assign(c, world["sup_a"].id, world["school"].id, start_date=str(today() + timedelta(days=5)))
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "assignment_overlap"
    # A different supervisor on the same school is allowed.
    assert assign(c, world["sup_b"].id, world["school"].id).status_code == 201


def test_cross_cluster_rules(world):
    c = world["head_client"]
    r = assign(c, world["sup_far"].id, world["school"].id)
    assert r.json()["error"]["code"] == "supervisor_other_cluster"
    # Another cluster's school is out of scope: 404.
    assert assign(c, world["sup_a"].id, world["far_school"].id).status_code == 404


def test_reassign_keeps_history(world, outbox):
    c = world["head_client"]
    a = assign(c, world["sup_a"].id, world["school"].id, start_date=str(today() - timedelta(days=30))).json()
    effective = today() + timedelta(days=1)
    r = c.post(
        f"/api/assignments/{a['id']}/reassign",
        json={
            "version": a["version"],
            "to_supervisor_id": world["sup_b"].id,
            "effective_date": str(effective),
            "reason": "Workload balance",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["supervisor"]["staff_id"] == "SB" and r.json()["start_date"] == str(effective)
    history = c.get("/api/assignments/history", params={"school_id": world["school"].id}).json()
    assert [(h["supervisor"]["staff_id"], h["start_date"], h["end_date"]) for h in history] == [
        ("SB", str(effective), None),
        ("SA", str(today() - timedelta(days=30)), str(today())),
    ]
    assert history[1]["end_reason"] == "Workload balance" and history[1]["ended_by"] == "head"
    with session_factory()() as db:
        types = sorted(n.type for n in db.execute(select(Notification)).scalars())
    assert types == ["assignment_ended", "assignment_started", "assignment_started"]


def test_concurrent_reassign_one_wins(world, new_client, outbox):
    """Two Cluster Heads reassign the same school at once: one succeeds, the other gets 409 with the current state."""
    c = world["head_client"]
    a = assign(c, world["sup_a"].id, world["school"].id).json()
    admin, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    results = {}
    barrier = threading.Barrier(2)

    def run(name, client, target):
        barrier.wait()
        results[name] = client.post(
            f"/api/assignments/{a['id']}/reassign",
            json={
                "version": a["version"],
                "to_supervisor_id": target,
                "reason": "change",
                "effective_date": str(today() + timedelta(days=1)),
            },
        )

    threads = [
        threading.Thread(target=run, args=("head", c, world["sup_b"].id)),
        threading.Thread(target=run, args=("admin", admin, world["sup_b"].id)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    codes = sorted(r.status_code for r in results.values())
    assert codes == [201, 409], [r.text for r in results.values()]
    loser = next(r for r in results.values() if r.status_code == 409)
    assert loser.json()["error"]["code"] == "version_conflict"
    assert loser.json()["error"]["detail"]["current"]["end_date"] == str(today())


def test_stale_version_rejected(world):
    c = world["head_client"]
    a = assign(c, world["sup_a"].id, world["school"].id).json()
    ok = c.post(
        f"/api/assignments/{a['id']}/end",
        json={"version": a["version"], "reason": "done", "end_date": str(today() + timedelta(days=3))},
    )
    assert ok.status_code == 200
    stale = c.post(f"/api/assignments/{a['id']}/end", json={"version": a["version"], "reason": "again"})
    assert stale.status_code == 409


def test_school_and_supervisor_deactivation_blocked_while_assigned(world, outbox):
    c = world["head_client"]
    a = assign(c, world["sup_a"].id, world["school"].id).json()
    r = c.post(f"/api/schools/{world['school'].id}/deactivate")
    assert r.json()["error"]["code"] == "school_has_assignments"
    r = c.post(f"/api/users/{world['user_a'].id}/deactivate")
    assert r.json()["error"]["code"] == "supervisor_has_assignments"
    # Ending today still covers today, so the block lifts tomorrow.
    c.post(f"/api/assignments/{a['id']}/end", json={"version": a["version"], "reason": "done"})
    clock.freeze(clock.now() + timedelta(days=1))
    login(c, outbox, "head@example.org")  # the old session timed out overnight
    assert c.post(f"/api/schools/{world['school'].id}/deactivate").status_code == 200


def test_supervisor_sees_only_assigned_schools_and_their_teachers(world, new_client, outbox):
    c = world["head_client"]
    teacher = c.post("/api/teachers", json=teacher_body(world["school"].id)).json()
    other_teacher = c.post(
        "/api/teachers", json=teacher_body(world["school2"].id, staff_id="T-2", email="t2@example.org")
    ).json()
    assign(c, world["sup_a"].id, world["school"].id)
    sup = new_client()
    login(sup, outbox, "a@example.org")
    schools = sup.get("/api/schools").json()["items"]
    assert [s["code"] for s in schools] == ["S1"]
    assert sup.get(f"/api/schools/{world['school2'].id}").status_code == 404
    assert [t["staff_id"] for t in sup.get("/api/teachers").json()["items"]] == ["T-100"]
    assert sup.get(f"/api/teachers/{teacher['id']}").status_code == 200
    assert sup.get(f"/api/teachers/{other_teacher['id']}").status_code == 404
    # Supervisors cannot change schools, teachers or assignments.
    assert sup.patch(f"/api/schools/{world['school'].id}", json={"version": 1, "name": "x"}).status_code == 403
    assert assign(sup, world["sup_a"].id, world["school2"].id).status_code == 403
    mine = sup.get("/api/me/assignments").json()
    assert [m["school"]["code"] for m in mine] == ["S1"]
    # Another supervisor's history is not visible.
    assert sup.get("/api/assignments/history", params={"supervisor_id": world["sup_b"].id}).status_code == 404


def test_board_shows_workload(world):
    c = world["head_client"]
    assign(c, world["sup_a"].id, world["school"].id)
    assign(c, world["sup_a"].id, world["school2"].id)
    assign(c, world["sup_b"].id, world["school"].id, start_date=str(today() + timedelta(days=10)))
    board = c.get("/api/assignments/board", params={"cluster_id": world["cluster"].id}).json()
    workload = {s["staff_id"]: s["active_schools"] for s in board["supervisors"]}
    assert workload == {"SA": 2, "SB": 0}
    s1 = next(s for s in board["schools"] if s["code"] == "S1")
    assert sorted(a["state"] for a in s1["assignments"]) == ["active", "upcoming"]
    assert (
        world["other_head_client"].get("/api/assignments/board", params={"cluster_id": world["cluster"].id}).status_code
        == 404
    )


def test_future_assignment_can_be_cancelled(world):
    c = world["head_client"]
    a = assign(c, world["sup_a"].id, world["school"].id, start_date=str(today() + timedelta(days=7))).json()
    r = c.post(f"/api/assignments/{a['id']}/end", json={"version": a["version"], "reason": "not needed"})
    assert r.status_code == 200
    # The empty window no longer blocks a new assignment for the same pair.
    assert (
        assign(c, world["sup_a"].id, world["school"].id, start_date=str(today() + timedelta(days=7))).status_code == 201
    )


def test_notification_center(world, new_client, outbox):
    assign(world["head_client"], world["sup_a"].id, world["school"].id)
    sup = new_client()
    login(sup, outbox, "a@example.org")
    inbox = sup.get("/api/notifications").json()
    assert inbox["unread"] == 1 and inbox["items"][0]["type"] == "assignment_started"
    assert inbox["items"][0]["payload"]["school_code"] == "S1"
    sup.post(f"/api/notifications/{inbox['items'][0]['id']}/read")
    assert sup.get("/api/notifications").json()["unread"] == 0
    # The email copy waits for the daily digest and shows the date as D/MM/YYYY.
    with session_factory()() as db:
        queue.build_digests(db)
    deliver_mail()
    digest = next(m for m in outbox if m.to == "a@example.org" and m.subject == "Your daily summary")
    d = today()
    assert f"{d.day}/{d.month:02d}/{d.year}" in digest.text
    # Turning a type off stops new notices on that channel.
    assert (
        sup.put(
            "/api/notifications/preferences", json={"type": "assignment_started", "channel": "in_app", "enabled": False}
        ).status_code
        == 204
    )
    assign(world["head_client"], world["sup_a"].id, world["school2"].id)
    assert sup.get("/api/notifications").json()["unread"] == 0
