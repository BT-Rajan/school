"""Scoring (FR-SC2, FR-SC3): rule sets per form version, scores on submission, and recorded
recalculation.

- Form Authors and District Admins draft rule sets and check them against the district's
  worked examples. Only an admin activates one, and only when every example matches.
- An evaluation is scored on the server when it is submitted, with the form's active rule
  set, and the score says which rule set gave it. An amendment re-scores it with that same
  rule set, so changing the answers never quietly changes the formula.
- Activating a new rule set changes no stored score. An admin recalculates, with a reason,
  and the recalculation is recorded with each changed score in the audit log.
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock, jobs
from app.audit import service as audit
from app.auth.deps import Principal
from app.errors import AppError, invalid, not_found
from app.forms import schema as form_schema
from app.models import (
    Evaluation,
    EvaluationSection,
    FormVersion,
    Job,
    Role,
    School,
    ScoreRecalculation,
    ScoreRuleSet,
    User,
)
from app.requests import service as requests

from . import rules as scoring

EDITORS = (Role.DISTRICT_ADMIN, Role.FORM_AUTHOR)
ADMINS = (Role.DISTRICT_ADMIN,)
SCORED = ("submitted", "amended")
BATCH = 200


class RuleSetIn(BaseModel):
    rules: dict[str, Any]
    note: str | None = Field(default=None, max_length=1000)


class RuleSetUpdate(RuleSetIn):
    version: int


class VersionIn(BaseModel):
    version: int


class RecalculateIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


def _require(principal: Principal, roles: tuple[Role, ...]) -> None:
    if principal.role not in roles:
        raise AppError(403, "forbidden")


def _form(db: Session, form_id: int) -> FormVersion:
    form = db.get(FormVersion, form_id)
    if form is None:
        raise not_found()
    return form


def _name(db: Session, user_id: int | None) -> str | None:
    return db.get(User, user_id).name if user_id else None


def rule_set_out(db: Session, rs: ScoreRuleSet, *, with_checks: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": rs.id,
        "form_id": rs.form_version_id,
        "number": rs.number,
        "status": rs.status,
        "rules": rs.rules,
        "note": rs.note,
        "created_by": _name(db, rs.created_by),
        "created_at": rs.created_at,
        "activated_by": _name(db, rs.activated_by),
        "activated_at": rs.activated_at,
        "retired_at": rs.retired_at,
        "version": rs.version,
    }
    if with_checks:
        out.update(check(db, rs))
    return out


def check(db: Session, rs: ScoreRuleSet) -> dict[str, Any]:
    """The rule set's problems against its form, and each worked example's result."""
    form = form_schema.parse(_form(db, rs.form_version_id).schema)
    parsed = scoring.parse(rs.rules)
    problems = scoring.problems(parsed, form)
    examples = scoring.check_examples(parsed, form) if not problems else []
    return {"problems": problems, "examples": examples}


def list_rule_sets(db: Session, principal: Principal, form_id: int) -> list[dict[str, Any]]:
    _require(principal, EDITORS)
    _form(db, form_id)
    rows = db.execute(
        select(ScoreRuleSet).where(ScoreRuleSet.form_version_id == form_id).order_by(ScoreRuleSet.number.desc())
    ).scalars()
    return [rule_set_out(db, rs) for rs in rows]


def get_rule_set(db: Session, principal: Principal, rule_set_id: int) -> ScoreRuleSet:
    _require(principal, EDITORS)
    rs = db.get(ScoreRuleSet, rule_set_id)
    if rs is None:
        raise not_found()
    return rs


def _locked(db: Session, rule_set_id: int, version: int) -> ScoreRuleSet:
    rs = db.execute(
        select(ScoreRuleSet)
        .where(ScoreRuleSet.id == rule_set_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if rs is None:
        raise not_found()
    if rs.version != version:
        raise AppError(409, "version_conflict", {"current": rule_set_out(db, rs)})
    return rs


def _audit(db: Session, action: str, rs: ScoreRuleSet, **after: Any) -> None:
    audit.record(
        db,
        action,
        entity_type="score_rule_set",
        entity_id=rs.id,
        after={"form_id": rs.form_version_id, "number": rs.number, **after},
    )


def create_rule_set(db: Session, principal: Principal, form_id: int, body: RuleSetIn) -> ScoreRuleSet:
    _require(principal, EDITORS)
    form = db.execute(select(FormVersion).where(FormVersion.id == form_id).with_for_update()).scalar_one_or_none()
    if form is None:
        raise not_found()
    scoring.parse(body.rules)
    number = (
        db.execute(select(func.max(ScoreRuleSet.number)).where(ScoreRuleSet.form_version_id == form_id)).scalar() or 0
    ) + 1
    rs = ScoreRuleSet(
        form_version_id=form_id, number=number, rules=body.rules, note=body.note, created_by=principal.user.id
    )
    db.add(rs)
    db.flush()
    _audit(db, "score_rules.created", rs)
    db.commit()
    return rs


def update_rule_set(db: Session, principal: Principal, rule_set_id: int, body: RuleSetUpdate) -> ScoreRuleSet:
    _require(principal, EDITORS)
    rs = _locked(db, rule_set_id, body.version)
    if rs.status != "draft":
        raise AppError(409, "rule_set_fixed")
    scoring.parse(body.rules)
    rs.rules, rs.note = body.rules, body.note
    db.flush()
    _audit(db, "score_rules.updated", rs)
    db.commit()
    return rs


def discard_rule_set(db: Session, principal: Principal, rule_set_id: int, body: VersionIn) -> ScoreRuleSet:
    _require(principal, EDITORS)
    rs = _locked(db, rule_set_id, body.version)
    if rs.status != "draft":
        raise AppError(409, "rule_set_fixed")
    rs.status = "discarded"
    db.flush()
    _audit(db, "score_rules.discarded", rs)
    db.commit()
    return rs


def activate(db: Session, principal: Principal, rule_set_id: int, body: VersionIn) -> ScoreRuleSet:
    """Make a checked rule set the form's formula. Stored scores stay as they are."""
    _require(principal, ADMINS)
    rs = _locked(db, rule_set_id, body.version)
    if rs.status != "draft":
        raise AppError(409, "rule_set_fixed")
    result = check(db, rs)
    if result["problems"]:
        raise invalid("rule_set_problems", result["problems"])
    if not result["examples"]:
        raise invalid("rule_set_needs_examples")
    if failed := [e["name"] for e in result["examples"] if not e["matches"]]:
        raise invalid("rule_set_examples_fail", [{"where": name, "code": "mismatch"} for name in failed])
    now = clock.now()
    for previous in db.execute(
        select(ScoreRuleSet)
        .where(ScoreRuleSet.form_version_id == rs.form_version_id, ScoreRuleSet.status == "active")
        .with_for_update()
    ).scalars():
        previous.status, previous.retired_at = "retired", now
        _audit(db, "score_rules.retired", previous, replaced_by=rs.id)
    rs.status, rs.activated_by, rs.activated_at = "active", principal.user.id, now
    db.flush()
    _audit(db, "score_rules.activated", rs, examples=len(result["examples"]))
    db.commit()
    return rs


# Scoring evaluations ---------------------------------------------------------------------


def active_rule_set(db: Session, form_id: int) -> ScoreRuleSet | None:
    return db.execute(
        select(ScoreRuleSet).where(ScoreRuleSet.form_version_id == form_id, ScoreRuleSet.status == "active")
    ).scalar_one_or_none()


def _answers(db: Session, e: Evaluation) -> tuple[dict[str, dict[str, Any]], set[str]]:
    answers = {
        s.section_key: s.answers
        for s in db.execute(select(EvaluationSection).where(EvaluationSection.evaluation_id == e.id)).scalars()
    }
    skipped = set()
    # A teacher's part counts once submitted; a waived one is left out of the score entirely.
    for s in requests.evaluation_sections(db, e):
        if s["status"] == "submitted":
            answers[s["key"]] = s["answers"]
        else:
            skipped.add(s["key"])
    return answers, skipped


def calculate(db: Session, e: Evaluation, rs: ScoreRuleSet) -> dict[str, Any]:
    form = form_schema.parse(db.get(FormVersion, e.form_version_id).schema)
    answers, skipped = _answers(db, e)
    result = scoring.calculate(scoring.parse(rs.rules), form, answers, skipped)
    return {**result, "rule_set_id": rs.id, "rule_set_number": rs.number, "calculated_at": clock.now().isoformat()}


def score_submitted(db: Session, e: Evaluation) -> None:
    """On submission: the active rule set's score, if the form has one yet."""
    rs = active_rule_set(db, e.form_version_id)
    e.score = calculate(db, e, rs) if rs else None


def score_amended(db: Session, e: Evaluation) -> None:
    """On amendment: the answers changed, the formula did not."""
    rs = db.get(ScoreRuleSet, e.score["rule_set_id"]) if e.score else active_rule_set(db, e.form_version_id)
    e.score = calculate(db, e, rs) if rs else None


def _same(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    strip = lambda s: {k: v for k, v in (s or {}).items() if k != "calculated_at"}  # noqa: E731
    return a is not None and b is not None and strip(a) == strip(b)


def recalculate(db: Session, principal: Principal, form_id: int, body: RecalculateIn) -> ScoreRecalculation:
    _require(principal, ADMINS)
    _form(db, form_id)
    rs = active_rule_set(db, form_id)
    if rs is None:
        raise AppError(409, "no_active_rule_set")
    running = db.execute(
        select(ScoreRecalculation.id).where(
            ScoreRecalculation.form_version_id == form_id, ScoreRecalculation.status.in_(("queued", "running"))
        )
    ).first()
    if running:
        raise AppError(409, "recalculation_running")
    recalc = ScoreRecalculation(
        form_version_id=form_id, rule_set_id=rs.id, reason=body.reason, requested_by=principal.user.id
    )
    db.add(recalc)
    db.flush()
    jobs.enqueue(db, "score_recalculation", {"recalculation_id": recalc.id}, principal.user.id)
    audit.record(
        db,
        "score.recalculation_requested",
        entity_type="score_recalculation",
        entity_id=recalc.id,
        after={"form_id": form_id, "rule_set_id": rs.id, "reason": body.reason},
    )
    db.commit()
    return recalc


def _recalculation_failed(db: Session, job: Job) -> None:
    recalc = db.get(ScoreRecalculation, job.payload["recalculation_id"])
    recalc.status, recalc.finished_at = "failed", clock.now()


@jobs.handler("score_recalculation", on_failure=_recalculation_failed)
def run_recalculation(db: Session, job: Job) -> dict[str, Any]:
    recalc = db.get(ScoreRecalculation, job.payload["recalculation_id"])
    rs = db.get(ScoreRuleSet, recalc.rule_set_id)
    recalc.status = "running"
    db.commit()
    after_id = 0
    while True:
        batch = list(
            db.execute(
                select(Evaluation)
                .where(
                    Evaluation.form_version_id == recalc.form_version_id,
                    Evaluation.status.in_(SCORED),
                    Evaluation.id > after_id,
                )
                .order_by(Evaluation.id)
                .limit(BATCH)
            ).scalars()
        )
        if not batch:
            break
        for e in batch:
            after_id = e.id
            recalc.evaluations += 1
            new = calculate(db, e, rs)
            if _same(e.score, new):
                continue
            before = e.score
            e.score = new
            recalc.changed += 1
            audit.record(
                db,
                "evaluation.rescored",
                entity_type="evaluation",
                entity_id=e.id,
                cluster_id=db.get(School, e.school_id).cluster_id,
                actor_id=recalc.requested_by,
                before={
                    "rule_set_id": before and before.get("rule_set_id"),
                    "points": before and before.get("points"),
                    "percent": before and before.get("percent"),
                },
                after={
                    "rule_set_id": rs.id,
                    "points": new["points"],
                    "percent": new["percent"],
                    "recalculation_id": recalc.id,
                },
            )
        db.commit()
    recalc.status, recalc.finished_at = "done", clock.now()
    audit.record(
        db,
        "score.recalculated",
        entity_type="score_recalculation",
        entity_id=recalc.id,
        actor_id=recalc.requested_by,
        after={"evaluations": recalc.evaluations, "changed": recalc.changed},
    )
    db.commit()
    return {"evaluations": recalc.evaluations, "changed": recalc.changed}


def recalculation_out(db: Session, r: ScoreRecalculation) -> dict[str, Any]:
    rs = db.get(ScoreRuleSet, r.rule_set_id)
    return {
        "id": r.id,
        "form_id": r.form_version_id,
        "rule_set": {"id": rs.id, "number": rs.number},
        "reason": r.reason,
        "status": r.status,
        "evaluations": r.evaluations,
        "changed": r.changed,
        "requested_by": _name(db, r.requested_by),
        "requested_at": r.requested_at,
        "finished_at": r.finished_at,
    }


def list_recalculations(db: Session, principal: Principal, form_id: int) -> list[dict[str, Any]]:
    _require(principal, ADMINS)
    rows = db.execute(
        select(ScoreRecalculation)
        .where(ScoreRecalculation.form_version_id == form_id)
        .order_by(ScoreRecalculation.id.desc())
    ).scalars()
    return [recalculation_out(db, r) for r in rows]
