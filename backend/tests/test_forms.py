from datetime import datetime

import pytest
from sqlalchemy import select

from app import clock
from app.db import session_factory
from app.forms import schema as fs
from app.models import AuditLog, MfaMethod, Notification, Role

from .helpers import login, make_user, sample_schema, signed_in


@pytest.fixture
def people(new_client, outbox):
    # 4/11/2026, 09:00 in Kuwait.
    clock.freeze(datetime(2026, 11, 4, 6, 0))
    author, author_user = signed_in(new_client, outbox, Role.FORM_AUTHOR, "author@example.org", mfa=MfaMethod.TOTP)
    admin, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    make_user(Role.SUPERVISOR, "sup@example.org", staff_id="S1")
    return {"author": author, "admin": admin, "author_user": author_user, "new_client": new_client, "outbox": outbox}


def draft_form(author, code="MOE-SV-01", version="2026.1", schema=None):
    report = author.post("/api/catalog/reports", json={"report_code": code, "subject_type": "school"})
    report_id = report.json()["id"] if report.status_code == 201 else None
    form = author.post(
        f"/api/catalog/reports/{report_id}/versions",
        json={"version_code": version, "title_en": "School visit report", "title_ar": "تقرير زيارة مدرسة"},
    )
    assert form.status_code == 201, form.text
    form = form.json()
    saved = author.patch(
        f"/api/forms/{form['id']}", json={"version": form["version"], "schema": schema or sample_schema()}
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def to_review(author, form):
    r = author.post(f"/api/forms/{form['id']}/submit", json={"version": form["version"]})
    assert r.status_code == 200, r.text
    return r.json()


def publish(admin, form, start, end, **extra):
    return admin.post(
        f"/api/forms/{form['id']}/publish",
        json={"version": form["version"], "start_date": start, "end_date": end, **extra},
    )


def test_structure_checked_on_save(people):
    form = draft_form(people["author"])
    bad = sample_schema()
    # A condition may only refer to an earlier question.
    bad["sections"][0]["questions"][0]["visible_if"] = {"question": "rating", "op": "answered"}
    r = people["author"].patch(f"/api/forms/{form['id']}", json={"version": form["version"], "schema": bad})
    assert r.status_code == 422 and r.json()["error"]["code"] == "form_schema_invalid"
    assert {"where": "visit.met_principal", "code": "condition_not_earlier"} in r.json()["error"]["detail"]
    r = people["author"].patch(
        f"/api/forms/{form['id']}",
        json={
            "version": form["version"],
            "schema": {"sections": [{"key": "Bad Key", "title": {"en": "x"}, "respondent": "supervisor"}]},
        },
    )
    assert r.json()["error"]["code"] == "form_schema_invalid"


def test_missing_arabic_blocks_review(people):
    form = draft_form(people["author"], schema=sample_schema(arabic=False))
    assert any(p["code"] == "arabic_missing" for p in form["problems"])
    r = people["author"].post(f"/api/forms/{form['id']}/submit", json={"version": form["version"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "form_incomplete"


def test_review_return_and_publish_window(people):
    author, admin = people["author"], people["admin"]
    form = to_review(author, draft_form(author))
    with session_factory()() as db:
        assert db.execute(select(Notification).where(Notification.type == "form_submitted_for_review")).first()
    # The admin returns it once with comments.
    r = admin.post(f"/api/forms/{form['id']}/return", json={"version": form["version"], "comment": "Fix question 3"})
    assert r.status_code == 200 and r.json()["status"] == "draft"
    assert author.get(f"/api/forms/{form['id']}/comments").json()[-1]["comment"] == "Fix question 3"
    form = to_review(author, r.json())
    # Published from 5/11/2026 to 30/11/2026, in district time.
    r = publish(admin, form, "2026-11-05", "2026-11-30")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "scheduled"
    form_id = form["id"]

    def status_on(utc: datetime) -> str:
        clock.freeze(utc)
        fresh = people["new_client"]()
        login(fresh, people["outbox"], "sup@example.org")
        return fresh.get(f"/api/forms/{form_id}").json()["status"]

    assert status_on(datetime(2026, 11, 4, 20, 59)) == "scheduled"  # 23:59 on 4/11 in Kuwait
    assert status_on(datetime(2026, 11, 4, 21, 0)) == "active"  # 00:00 on 5/11
    assert status_on(datetime(2026, 11, 30, 20, 59)) == "active"  # 23:59 on 30/11
    assert status_on(datetime(2026, 11, 30, 21, 0)) == "closed"  # 00:00 on 1/12


def test_published_content_is_locked_and_window_changes_audited(people):
    author, admin = people["author"], people["admin"]
    form = publish(admin, to_review(author, draft_form(author)), "2026-11-05", "2026-11-30").json()
    r = author.patch(f"/api/forms/{form['id']}", json={"version": form["version"], "schema": sample_schema()})
    assert r.json()["error"]["code"] == "form_not_draft"
    r = admin.post(
        f"/api/forms/{form['id']}/extend",
        json={"version": form["version"], "end_date": "2026-12-10", "reason": "Exams moved"},
    )
    assert r.status_code == 200 and r.json()["end_date"] == "2026-12-10"
    with session_factory()() as db:
        entry = db.execute(select(AuditLog).where(AuditLog.action == "form.window_extended")).scalar_one()
        assert entry.after["before"] == "2026-11-30"
        notices = db.execute(select(Notification).where(Notification.type == "form_window_changed")).scalars().all()
        assert notices
    r = admin.post(f"/api/forms/{form['id']}/close", json={"version": r.json()["version"], "reason": "Cancelled"})
    assert r.json()["status"] == "closed"


def test_only_admins_publish_and_only_authors_build(people):
    author, admin = people["author"], people["admin"]
    form = to_review(author, draft_form(author))
    assert publish(author, form, "2026-11-05", "2026-11-30").status_code == 403
    assert admin.post("/api/catalog/reports", json={"report_code": "X", "subject_type": "school"}).status_code == 403
    bad = publish(admin, form, "2026-11-03", "2026-11-30")
    assert bad.json()["error"]["code"] == "start_in_past"
    bad = publish(admin, form, "2026-11-10", "2026-11-05")
    assert bad.json()["error"]["code"] == "end_before_start"


def test_overlapping_versions_need_confirmation(people):
    author, admin = people["author"], people["admin"]
    first = publish(admin, to_review(author, draft_form(author)), "2026-11-05", "2026-11-30").json()
    copy = author.post(
        f"/api/catalog/reports/{first['report']['id']}/versions",
        json={
            "version_code": "2026.2",
            "title_en": "School visit report v2",
            "title_ar": "تقرير زيارة مدرسة 2",
            "copy_from_form_id": first["id"],
        },
    ).json()
    # FR-MR4: the new version starts from a copy of the previous form.
    assert copy["schema"] == first["schema"] and copy["status"] == "draft"
    second = to_review(author, copy)
    r = publish(admin, second, "2026-11-20", "2026-12-20")
    assert r.status_code == 409 and r.json()["error"]["code"] == "window_overlap"
    assert r.json()["error"]["detail"]["forms"][0]["version_code"] == "2026.1"
    assert publish(admin, second, "2026-11-20", "2026-12-20", confirm_overlap=True).status_code == 200


def test_supervisors_see_published_forms_only(people):
    author, admin = people["author"], people["admin"]
    draft = draft_form(author, code="DRAFT-1")
    published = publish(admin, to_review(author, draft_form(author, code="PUB-1")), "2026-11-05", "2026-11-30").json()
    sup = people["new_client"]()
    login(sup, people["outbox"], "sup@example.org")
    assert [f["id"] for f in sup.get("/api/forms").json()] == [published["id"]]
    assert sup.get(f"/api/forms/{draft['id']}").status_code == 404
    assert "problems" not in sup.get(f"/api/forms/{published['id']}").json()
    catalog = sup.get("/api/catalog").json()
    assert [r["report_code"] for r in catalog] == ["PUB-1"]
    assert sup.post("/api/catalog/reports", json={"report_code": "Z", "subject_type": "school"}).status_code == 403


# Answer validation -----------------------------------------------------------------------


def test_answers_follow_the_schema():
    form = fs.parse(sample_schema())
    good = {
        "met_principal": True,
        "classrooms": 4,
        "rating": 5,
        "areas": ["safety"],
        "staff": [{"name": "Ali", "present": True}],
        "reason_not_met": "ignored when hidden",
    }
    cleaned, problems = fs.validate_answers(form, "visit", good, complete=True)
    assert problems == []
    # The hidden question's answer is dropped.
    assert "reason_not_met" not in cleaned
    _, problems = fs.validate_answers(
        form,
        "visit",
        {"met_principal": False, "classrooms": 99, "rating": 2.5, "areas": ["unknown"], "staff": [{"present": "yes"}]},
        complete=True,
    )
    codes = {(p["where"], p["code"]) for p in problems}
    assert ("reason_not_met", "required") in codes  # now visible and required
    assert ("classrooms", "above_max") in codes
    assert ("rating", "not_whole") in codes
    assert ("areas", "not_an_option") in codes
    assert ("staff.0.name", "required") in codes
    assert ("staff.0.present", "not_yes_no") in codes
    # Drafts may leave required answers empty.
    _, problems = fs.validate_answers(form, "visit", {}, complete=False)
    assert problems == []
