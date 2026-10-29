from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import clock, jobs
from app.db import session_factory
from app.forms import schema as form_schema
from app.models import AuditLog, Evaluation, MfaMethod, Role, ScoreRecalculation
from app.scoring import rules as scoring

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
)

TODAY = datetime(2026, 11, 10).date()
FORM = form_schema.parse(sample_schema())

RULES = {
    "questions": {
        "met_principal": {"points": {"yes": 1, "no": 0}},
        # The form gives classrooms a weight of 2.
        "classrooms": {
            "ranges": [
                {"min": 0, "max": 2, "points": 0},
                {"min": 3, "max": 10, "points": 2},
                {"min": 11, "max": 50, "points": 3},
            ]
        },
        "rating": {"value": True},
        "areas": {"points": {"safety": 1, "teaching": 2}},
    },
    "bands": [
        {"min": 90, "label": {"en": "Excellent", "ar": "ممتاز"}},
        {"min": 75, "label": {"en": "Good", "ar": "جيد"}},
        {"min": 0, "label": {"en": "Needs support", "ar": "يحتاج إلى دعم"}},
    ],
}
ANSWERS = {"met_principal": True, "classrooms": 6, "rating": 4, "areas": ["safety", "teaching"], "notes": "x"}


def calc(rules: dict, answers: dict, **kw):
    return scoring.calculate(scoring.parse(rules), FORM, {"visit": answers}, **kw)


# The formula --------------------------------------------------------------------------------


def test_points_ranges_values_weights_and_bands():
    got = calc(RULES, ANSWERS)
    # 1 of 1, 2x2 of 2x3, 4 of 5, 3 of 3.
    assert (got["points"], got["max"], got["percent"]) == (12, 15, 80)
    assert got["band"] == {"en": "Good", "ar": "جيد"}
    assert got["sections"] == {"visit": {"points": 12, "max": 15}}


def test_missing_answers_left_out_or_counted_as_zero():
    answers = {k: v for k, v in ANSWERS.items() if k != "rating"}
    assert calc(RULES, answers)["percent"] == 80  # 8 of 10
    assert calc({**RULES, "missing": "zero"}, answers)["percent"] == 53.33  # 8 of 15


def test_every_scored_question_counts_and_rounding_is_half_up():
    rules = {"questions": {"met_principal": {"points": {"yes": 1, "no": 0}}, "rating": {"value": True, "max": 3}}}
    assert calc(rules, {"met_principal": False, "rating": 0})["percent"] == 0
    # 1 of 3 is 33.333...; 2 of 3 is 66.666... and rounds up.
    assert calc(rules, {"met_principal": False, "rating": 1})["percent"] == 25
    assert calc({**rules, "decimals": 2}, {"met_principal": True, "rating": 1})["percent"] == 50
    third = {"questions": {"rating": {"value": True, "max": 3}}}
    assert calc(third, {"rating": 1})["percent"] == 33.33
    assert calc(third, {"rating": 2})["percent"] == 66.67
    assert calc({**third, "decimals": 0}, {"rating": 2})["percent"] == 67


def test_section_weights_and_skipped_sections():
    form = form_schema.parse(sample_schema(teacher_section=True))
    teacher_q = {"key": "useful", "type": "yes_no", "label": {"en": "Useful?", "ar": "مفيد؟"}}
    raw = sample_schema(teacher_section=True)
    raw["sections"][1]["questions"].append(teacher_q)
    form = form_schema.parse(raw)
    rules = scoring.parse(
        {
            "questions": {"rating": {"value": True}, "useful": {"points": {"yes": 5, "no": 0}}},
            "sections": {"self": {"weight": 2}},
        }
    )
    both = scoring.calculate(rules, form, {"visit": {"rating": 5}, "self": {"useful": False}})
    assert (both["points"], both["max"]) == (5, 15)
    waived = scoring.calculate(rules, form, {"visit": {"rating": 5}}, {"self"})
    assert (waived["points"], waived["max"], waived["percent"]) == (5, 5, 100)


def test_rule_set_problems_against_the_form():
    bad = scoring.parse(
        {
            "questions": {
                "nope": {"value": True},
                "staff": {"value": True},
                "areas": {"points": {"safety": 1, "cooking": 2}},
                "met_principal": {"value": True},
                "classrooms": {"ranges": [{"min": 5, "max": 1, "points": 1}]},
            },
            "sections": {"ghost": {"weight": 1}},
        }
    )
    codes = {(p["where"], p["code"]) for p in scoring.problems(bad, FORM)}
    assert codes == {
        ("questions.nope", "question_unknown"),
        ("questions.staff", "question_not_scorable"),
        ("questions.areas", "option_unknown"),
        ("questions.met_principal", "value_needs_number"),
        ("questions.classrooms", "range_reversed"),
        ("sections.ghost", "section_unknown"),
    }
    with pytest.raises(Exception) as caught:
        scoring.parse({"questions": {"rating": {"value": True, "points": {"a": 1}}}})
    assert getattr(caught.value, "code", "") == "rule_set_invalid"


# Rule sets, submission and recalculation ------------------------------------------------------


@pytest.fixture
def world(new_client, outbox):
    clock.freeze(datetime(2026, 11, 10, 6, 0))
    seed_reference()
    _, head_user = signed_in(new_client, outbox, Role.CLUSTER_HEAD, "head@example.org", staff_id="CH")
    admin, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    author, _ = signed_in(new_client, outbox, Role.FORM_AUTHOR, "author@example.org")
    cluster = make_cluster("C1", head_user)
    school = make_school(cluster, "S1")
    sup, _ = make_supervisor(cluster, "a@example.org", "SA")
    assign_direct(sup.id, school.id, TODAY - timedelta(days=30))
    form_id = publish_direct(sample_schema(), TODAY - timedelta(days=5), TODAY + timedelta(days=20))
    a = new_client()
    login(a, outbox, "a@example.org")
    return {"admin": admin, "author": author, "a": a, "school": school, "form_id": form_id}


EXAMPLE = {"name": "District example 1", "answers": {"visit": ANSWERS}, "expected": {"percent": 80, "band": "Good"}}


def submitted_evaluation(w) -> dict:
    a = w["a"]
    e = a.post(
        "/api/evaluations", json={"form_id": w["form_id"], "school_id": w["school"].id, "visit_date": str(TODAY)}
    ).json()
    answers = {**ANSWERS, "staff": [{"name": "Ali", "present": True}]}
    e = a.patch(f"/api/evaluations/{e['id']}", json={"version": e["version"], "sections": {"visit": answers}}).json()
    r = a.post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"]})
    assert r.status_code == 200, r.text
    return r.json()


def test_activation_needs_matching_examples_and_scores_are_fixed_until_recalculated(world):
    admin, author, a = world["admin"], world["author"], world["a"]
    form_id = world["form_id"]
    # Only builders draft rule sets; supervisors cannot.
    assert a.post(f"/api/forms/{form_id}/rule-sets", json={"rules": RULES}).status_code == 403

    # Submitted before any formula: no score yet.
    first = submitted_evaluation(world)
    assert first["score"] is None

    rs = author.post(f"/api/forms/{form_id}/rule-sets", json={"rules": RULES, "note": "From the district"}).json()
    assert rs["number"] == 1 and rs["status"] == "draft" and rs["problems"] == [] and rs["examples"] == []
    # Only an admin activates, and only with worked examples that match.
    assert author.post(f"/api/rule-sets/{rs['id']}/activate", json={"version": rs["version"]}).status_code == 403
    r = admin.post(f"/api/rule-sets/{rs['id']}/activate", json={"version": rs["version"]})
    assert r.json()["error"]["code"] == "rule_set_needs_examples"
    wrong = {**EXAMPLE, "expected": {"percent": 81}}
    rs = author.patch(
        f"/api/rule-sets/{rs['id']}", json={"version": rs["version"], "rules": {**RULES, "examples": [wrong]}}
    ).json()
    assert rs["examples"][0]["matches"] is False and rs["examples"][0]["result"]["percent"] == 80
    r = admin.post(f"/api/rule-sets/{rs['id']}/activate", json={"version": rs["version"]})
    assert r.json()["error"]["code"] == "rule_set_examples_fail"
    rs = author.patch(
        f"/api/rule-sets/{rs['id']}", json={"version": rs["version"], "rules": {**RULES, "examples": [EXAMPLE]}}
    ).json()
    rs = admin.post(f"/api/rule-sets/{rs['id']}/activate", json={"version": rs["version"]}).json()
    assert rs["status"] == "active" and rs["activated_by"]
    # An active rule set is fixed.
    r = author.patch(f"/api/rule-sets/{rs['id']}", json={"version": rs["version"], "rules": RULES})
    assert r.json()["error"]["code"] == "rule_set_fixed"

    # Activation changed no stored score; a new submission is scored on the server.
    assert a.get(f"/api/evaluations/{first['id']}").json()["score"] is None
    second = submitted_evaluation(world)
    assert second["score"]["percent"] == 80 and second["score"]["rule_set_number"] == 1
    assert second["score"]["band"]["en"] == "Good"

    # A second rule set: rating counts double.
    rules2 = {**RULES, "questions": {**RULES["questions"], "rating": {"value": True, "weight": 2}}}
    example2 = {**EXAMPLE, "expected": {"points": 16, "percent": 80}}
    rs2 = admin.post(f"/api/forms/{form_id}/rule-sets", json={"rules": {**rules2, "examples": [example2]}}).json()
    assert rs2["number"] == 2 and rs2["examples"][0]["matches"]
    admin.post(f"/api/rule-sets/{rs2['id']}/activate", json={"version": rs2["version"]})
    assert [x["status"] for x in admin.get(f"/api/forms/{form_id}/rule-sets").json()] == ["active", "retired"]
    assert a.get(f"/api/evaluations/{second['id']}").json()["score"]["rule_set_number"] == 1

    # Recalculating is recorded, and changes the scores that differ.
    assert a.post(f"/api/forms/{form_id}/recalculations", json={"reason": "New formula"}).status_code == 403
    r = admin.post(f"/api/forms/{form_id}/recalculations", json={"reason": "Ministry formula 2026.2"})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert (
        admin.post(f"/api/forms/{form_id}/recalculations", json={"reason": "again"}).json()["error"]["code"]
        == "recalculation_running"
    )
    with session_factory()() as db:
        assert jobs.run_next(db)
    done = admin.get(f"/api/forms/{form_id}/recalculations").json()[0]
    assert (done["status"], done["evaluations"], done["changed"]) == ("done", 2, 2)
    for e in (first, second):
        score = a.get(f"/api/evaluations/{e['id']}").json()["score"]
        assert (score["rule_set_number"], score["points"], score["max"]) == (2, 16, 20)
    with session_factory()() as db:
        rescored = db.execute(select(AuditLog).where(AuditLog.action == "evaluation.rescored")).scalars().all()
        assert len(rescored) == 2
        assert {r.before["points"] for r in rescored} == {None, "12.0"}  # the audit keeps values as text
        assert db.execute(select(ScoreRecalculation)).scalar_one().reason == "Ministry formula 2026.2"
    # Nothing differs a second time, so nothing changes.
    admin.post(f"/api/forms/{form_id}/recalculations", json={"reason": "Check"})
    with session_factory()() as db:
        jobs.run_next(db)
    assert admin.get(f"/api/forms/{form_id}/recalculations").json()[0]["changed"] == 0


def test_amendment_rescores_with_the_same_rule_set(world):
    admin, a = world["admin"], world["a"]
    rs = admin.post(f"/api/forms/{world['form_id']}/rule-sets", json={"rules": {**RULES, "examples": [EXAMPLE]}}).json()
    admin.post(f"/api/rule-sets/{rs['id']}/activate", json={"version": rs["version"]})
    e = submitted_evaluation(world)
    # A newer formula is activated but not recalculated.
    rules2 = {**RULES, "questions": {"rating": {"value": True}}, "examples": [{**EXAMPLE, "expected": {"percent": 80}}]}
    rs2 = admin.post(f"/api/forms/{world['form_id']}/rule-sets", json={"rules": rules2}).json()
    admin.post(f"/api/rule-sets/{rs2['id']}/activate", json={"version": rs2["version"]})
    r = a.post(
        f"/api/evaluations/{e['id']}/amend",
        json={"version": e["version"], "reason": "Wrong rating", "sections": {"visit": {**ANSWERS, "rating": 2}}},
    )
    assert r.status_code == 200, r.text
    score = r.json()["score"]
    assert (score["rule_set_number"], score["points"], score["max"]) == (1, 10, 15)
    with session_factory()() as db:
        assert db.get(Evaluation, e["id"]).score["percent"] == 66.67
        amended = db.execute(select(AuditLog).where(AuditLog.action == "evaluation.amended")).scalar_one()
        assert (amended.after["score_before"], amended.after["score_after"]) == ("12.0", "10.0")


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_scored_evaluation_pdf(world, locale):
    admin, a = world["admin"], world["a"]
    rs = admin.post(f"/api/forms/{world['form_id']}/rule-sets", json={"rules": {**RULES, "examples": [EXAMPLE]}}).json()
    admin.post(f"/api/rule-sets/{rs['id']}/activate", json={"version": rs["version"]})
    e = submitted_evaluation(world)
    r = a.get(f"/api/evaluations/{e['id']}/pdf", params={"locale": locale})
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
