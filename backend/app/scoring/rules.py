"""Scoring rule sets (FR-SC2, FR-SC3): what the district's formula says, as data.

A rule set belongs to one form version and says, for each scored question, how its answer
becomes points, and how points add up:

- choice and yes/no questions: points per option (``points``); a multi-choice answer earns
  the sum of the options chosen.
- number and rating questions: the answer itself (``value``), or points by range (``ranges``).
- every question has a weight (the rule's, else the form's ``score_weight``, else 1), and
  every section a weight (default 1).
- ``missing``: an unanswered or hidden question is left out of the maximum too
  ("exclude"), or scores 0 of its maximum ("zero"). A hidden question is always left out.
- the total is points out of the maximum, as a percentage, with optional bands
  ("Excellent" from 90%, ...).

Rule sets carry the district's worked examples; one cannot be activated until it gives the
expected result for each (the Phase 5 exit criterion). Arithmetic is decimal, rounded half up
only at the end, so the same answers always give the same score.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.errors import invalid
from app.forms.schema import FormSchema, Question, Text, _empty, _visible

KEY = r"^[a-z][a-z0-9_]{0,63}$"
SCORED_TYPES = ("single_choice", "multi_choice", "yes_no", "number", "rating")
MAX_EXAMPLES = 50


class Range(BaseModel):
    """Points for a number in [min, max]; both ends included."""

    min: float
    max: float
    points: float


class QuestionRule(BaseModel):
    points: dict[str, float] | None = None
    value: bool = False
    ranges: list[Range] | None = Field(default=None, max_length=50)
    max: float | None = Field(default=None, gt=0)
    weight: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def one_method(self) -> "QuestionRule":
        chosen = sum([self.points is not None, self.value, self.ranges is not None])
        if chosen != 1:
            raise ValueError("choose exactly one of points, value or ranges")
        return self


class SectionRule(BaseModel):
    weight: float = Field(default=1, ge=0)


class Band(BaseModel):
    min: float = Field(ge=0, le=100)
    label: Text


class Expected(BaseModel):
    points: float | None = None
    percent: float | None = None
    band: str | None = None  # the band's English label

    @model_validator(mode="after")
    def something(self) -> "Expected":
        if self.points is None and self.percent is None and self.band is None:
            raise ValueError("expect a points, percent or band result")
        return self


class Example(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    answers: dict[str, dict[str, Any]]  # section key -> question key -> answer
    expected: Expected


class RuleSet(BaseModel):
    questions: dict[str, QuestionRule] = Field(default_factory=dict)
    sections: dict[str, SectionRule] = Field(default_factory=dict)
    missing: Literal["exclude", "zero"] = "exclude"
    decimals: int = Field(default=2, ge=0, le=4)
    bands: list[Band] = Field(default_factory=list, max_length=20)
    examples: list[Example] = Field(default_factory=list, max_length=MAX_EXAMPLES)


def parse(raw: dict[str, Any]) -> RuleSet:
    try:
        return RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise invalid(
            "rule_set_invalid",
            [{"where": ".".join(str(p) for p in e["loc"]), "code": e["type"]} for e in exc.errors()],
        ) from exc


def _questions(form: FormSchema) -> dict[str, tuple[str, Question]]:
    return {q.key: (s.key, q) for s in form.sections for q in s.questions}


def _answer_codes(q: Question) -> set[str]:
    if q.type == "yes_no":
        return {"yes", "no"}
    return {o.code for o in q.options}


def problems(rules: RuleSet, form: FormSchema) -> list[dict[str, str]]:
    """Ways the rule set doesn't fit its form; a rule set with problems cannot be activated."""
    found: list[dict[str, str]] = []
    questions = _questions(form)
    sections = {s.key for s in form.sections}
    if not rules.questions:
        found.append({"where": "questions", "code": "nothing_scored"})
    for key, rule in rules.questions.items():
        where = f"questions.{key}"
        if key not in questions:
            found.append({"where": where, "code": "question_unknown"})
            continue
        q = questions[key][1]
        if q.type not in SCORED_TYPES:
            found.append({"where": where, "code": "question_not_scorable"})
            continue
        if rule.points is not None:
            if q.type not in ("single_choice", "multi_choice", "yes_no"):
                found.append({"where": where, "code": "points_need_choices"})
            elif unknown := set(rule.points) - _answer_codes(q):
                found.append({"where": where, "code": "option_unknown", "detail": ",".join(sorted(unknown))})
        if rule.value or rule.ranges is not None:
            if q.type not in ("number", "rating"):
                found.append({"where": where, "code": "value_needs_number"})
            elif rule.value and rule.max is None and q.max is None:
                found.append({"where": where, "code": "maximum_needed"})
        if rule.ranges is not None and any(r.min > r.max for r in rule.ranges):
            found.append({"where": where, "code": "range_reversed"})
    for key in rules.sections:
        if key not in sections:
            found.append({"where": f"sections.{key}", "code": "section_unknown"})
    mins = [b.min for b in rules.bands]
    if len(set(mins)) != len(mins):
        found.append({"where": "bands", "code": "bands_overlap"})
    return found


def _d(x: float | int) -> Decimal:
    return Decimal(str(x))


def _question_max(q: Question, rule: QuestionRule) -> Decimal:
    if rule.max is not None:
        return _d(rule.max)
    if rule.points is not None:
        values = [_d(v) for v in rule.points.values()]
        if q.type == "multi_choice":
            return sum((v for v in values if v > 0), Decimal(0))
        return max(values, default=Decimal(0))
    if rule.ranges is not None:
        return max((_d(r.points) for r in rule.ranges), default=Decimal(0))
    return _d(q.max or 0)


def _question_points(q: Question, rule: QuestionRule, answer: Any) -> Decimal:
    if rule.points is not None:
        if q.type == "yes_no":
            return _d(rule.points.get("yes" if answer else "no", 0))
        chosen = answer if isinstance(answer, list) else [answer]
        return sum((_d(rule.points.get(c, 0)) for c in chosen), Decimal(0))
    if rule.ranges is not None:
        for r in rule.ranges:
            if r.min <= answer <= r.max:
                return _d(r.points)
        return Decimal(0)
    return min(_d(answer), _question_max(q, rule))


def _round(x: Decimal, decimals: int) -> float:
    return float(x.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP))


def calculate(
    rules: RuleSet, form: FormSchema, answers: dict[str, dict[str, Any]], skipped: set[str] = frozenset()
) -> dict[str, Any]:
    """Score one evaluation. ``answers`` is section key -> accepted answers; sections in
    ``skipped`` (a waived teacher part) are left out entirely."""
    total = Decimal(0)
    total_max = Decimal(0)
    sections: dict[str, dict[str, float]] = {}
    for s in form.sections:
        if s.key in skipped:
            continue
        given = answers.get(s.key) or {}
        points = Decimal(0)
        maximum = Decimal(0)
        scored = False
        for q in s.questions:
            rule = rules.questions.get(q.key)
            if rule is None:
                continue
            weight = _d(rule.weight if rule.weight is not None else q.score_weight if q.score_weight is not None else 1)
            # Hidden questions never count; the answers given decide what was shown.
            if not _visible(q, given):
                continue
            answer = given.get(q.key)
            if _empty(answer):
                if rules.missing == "exclude":
                    continue
                maximum += _question_max(q, rule) * weight
                scored = True
                continue
            points += _question_points(q, rule, answer) * weight
            maximum += _question_max(q, rule) * weight
            scored = True
        if not scored:
            continue
        section_weight = _d(rules.sections.get(s.key, SectionRule()).weight)
        sections[s.key] = {"points": _round(points, rules.decimals), "max": _round(maximum, rules.decimals)}
        total += points * section_weight
        total_max += maximum * section_weight
    percent = total / total_max * 100 if total_max > 0 else None
    band = None
    if percent is not None:
        rounded = _d(_round(percent, rules.decimals))
        for b in sorted(rules.bands, key=lambda b: b.min, reverse=True):
            if rounded >= _d(b.min):
                band = b.label.model_dump()
                break
    return {
        "points": _round(total, rules.decimals),
        "max": _round(total_max, rules.decimals),
        "percent": _round(percent, rules.decimals) if percent is not None else None,
        "band": band,
        "sections": sections,
    }


def check_examples(rules: RuleSet, form: FormSchema) -> list[dict[str, Any]]:
    """Each worked example's result against what the district expects."""
    results = []
    for example in rules.examples:
        got = calculate(rules, form, example.answers)
        want = example.expected
        mismatches = []
        if want.points is not None and got["points"] != _round(_d(want.points), rules.decimals):
            mismatches.append("points")
        if want.percent is not None and got["percent"] != _round(_d(want.percent), rules.decimals):
            mismatches.append("percent")
        if want.band is not None and (got["band"] or {}).get("en") != want.band:
            mismatches.append("band")
        results.append({"name": example.name, "result": got, "matches": not mismatches, "mismatches": mismatches})
    return results
