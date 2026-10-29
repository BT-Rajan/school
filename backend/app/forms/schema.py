"""Form definitions and answer validation (FR-F2 to FR-F9).

A form is JSON: sections, each with a respondent, holding questions. The
builder writes it and the renderer reads it. The server validates it in two
strengths:

- structure: checked on every save (keys, types, conditions). Drafts may be
  incomplete, for example missing Arabic text.
- complete: checked before review. Every label has English and Arabic text
  and every section has at least one question (FR-F7).

Answers are validated here too, so the server alone decides what is valid.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.errors import invalid

KEY = r"^[a-z][a-z0-9_]{0,63}$"
QuestionType = Literal[
    "short_text", "long_text", "number", "single_choice", "multi_choice", "date", "yes_no", "rating", "table", "file"
]
ColumnType = Literal["short_text", "number", "date", "yes_no", "single_choice"]
CHOICE_TYPES = ("single_choice", "multi_choice")


class Text(BaseModel):
    en: str = ""
    ar: str = ""


class Option(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
    label: Text


class Condition(BaseModel):
    """Show the question only when an earlier answer matches (FR-F6)."""

    question: str = Field(pattern=KEY)
    op: Literal["equals", "not_equals", "in", "answered"]
    value: Any = None


class Column(BaseModel):
    key: str = Field(pattern=KEY)
    type: ColumnType
    label: Text
    required: bool = False
    options: list[Option] = Field(default_factory=list)


class Question(BaseModel):
    key: str = Field(pattern=KEY)
    type: QuestionType
    label: Text
    help: Text | None = None
    required: bool = False
    # number: min, max; short/long text: max_length; rating: min, max; table: max_rows; file: max_files
    min: float | None = None
    max: float | None = None
    max_length: int | None = Field(default=None, ge=1, le=10000)
    max_rows: int | None = Field(default=None, ge=1, le=200)
    max_files: int | None = Field(default=None, ge=1, le=20)
    options: list[Option] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)
    visible_if: Condition | None = None
    # FR-F8: weight for the district's scoring formula, applied in Phase 5.
    score_weight: float | None = None


class Section(BaseModel):
    key: str = Field(pattern=KEY)
    title: Text
    description: Text | None = None
    respondent: Literal["supervisor", "teacher"]
    questions: list[Question] = Field(default_factory=list)


class FormSchema(BaseModel):
    sections: list[Section] = Field(default_factory=list)


def _text_problems(text: Text | None, where: str, *, required: bool = True) -> list[dict[str, str]]:
    if text is None:
        return [{"where": where, "code": "text_missing"}] if required else []
    problems = []
    if not text.en.strip():
        problems.append({"where": where, "code": "english_missing"})
    if not text.ar.strip():
        problems.append({"where": where, "code": "arabic_missing"})
    return problems


def parse(raw: dict[str, Any]) -> FormSchema:
    try:
        return FormSchema.model_validate(raw)
    except ValidationError as exc:
        raise invalid(
            "form_schema_invalid",
            [{"where": ".".join(str(p) for p in e["loc"]), "code": e["type"]} for e in exc.errors()],
        ) from exc


def structure_problems(form: FormSchema) -> list[dict[str, str]]:
    """Problems that make a form unusable, checked on every save."""
    problems: list[dict[str, str]] = []
    section_keys: set[str] = set()
    question_keys: set[str] = set()
    for s in form.sections:
        if s.key in section_keys:
            problems.append({"where": s.key, "code": "duplicate_key"})
        section_keys.add(s.key)
        earlier_in_section: set[str] = set()
        for q in s.questions:
            where = f"{s.key}.{q.key}"
            if q.key in question_keys:
                problems.append({"where": where, "code": "duplicate_key"})
            if q.type in CHOICE_TYPES and not q.options:
                problems.append({"where": where, "code": "options_required"})
            if len({o.code for o in q.options}) != len(q.options):
                problems.append({"where": where, "code": "options_duplicate"})
            if q.type == "table":
                if not q.columns:
                    problems.append({"where": where, "code": "columns_required"})
                if len({c.key for c in q.columns}) != len(q.columns):
                    problems.append({"where": where, "code": "duplicate_key"})
                for c in q.columns:
                    if c.type == "single_choice" and not c.options:
                        problems.append({"where": f"{where}.{c.key}", "code": "options_required"})
            if q.type == "rating" and (q.min is None or q.max is None or q.min >= q.max):
                problems.append({"where": where, "code": "rating_range_invalid"})
            if q.min is not None and q.max is not None and q.min > q.max:
                problems.append({"where": where, "code": "range_invalid"})
            if q.visible_if is not None and q.visible_if.question not in earlier_in_section:
                # Each section is answered and checked on its own, so conditions refer to
                # earlier questions in the same section.
                problems.append({"where": where, "code": "condition_not_earlier"})
            question_keys.add(q.key)
            earlier_in_section.add(q.key)
    return problems


def completeness_problems(form: FormSchema) -> list[dict[str, str]]:
    """Everything a form needs before review: both languages everywhere, no empty sections."""
    problems = structure_problems(form)
    if not form.sections:
        problems.append({"where": "form", "code": "no_sections"})
    if not any(s.respondent == "supervisor" for s in form.sections):
        problems.append({"where": "form", "code": "no_supervisor_section"})
    for s in form.sections:
        problems += _text_problems(s.title, s.key)
        problems += _text_problems(s.description, f"{s.key}.description", required=False) if s.description else []
        if not s.questions:
            problems.append({"where": s.key, "code": "no_questions"})
        for q in s.questions:
            where = f"{s.key}.{q.key}"
            problems += _text_problems(q.label, where)
            if q.help is not None:
                problems += _text_problems(q.help, f"{where}.help")
            for o in q.options:
                problems += _text_problems(o.label, f"{where}.{o.code}")
            for c in q.columns:
                problems += _text_problems(c.label, f"{where}.{c.key}")
                for o in c.options:
                    problems += _text_problems(o.label, f"{where}.{c.key}.{o.code}")
    return problems


def copy_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """FR-MR4: a new version starts from a copy of the previous form."""
    return parse(raw).model_dump(mode="json")


# Answers ---------------------------------------------------------------------------


def _visible(q: Question, answers: dict[str, Any]) -> bool:
    c = q.visible_if
    if c is None:
        return True
    given = answers.get(c.question)
    if c.op == "answered":
        return given not in (None, "", [], {})
    if c.op == "equals":
        return given == c.value
    if c.op == "not_equals":
        return given != c.value
    values = c.value if isinstance(c.value, list) else [c.value]
    if isinstance(given, list):
        return any(v in values for v in given)
    return given in values


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _check_scalar(kind: str, value: Any, *, options: list[Option], q: Question | Column) -> str | None:
    codes = {o.code for o in options}
    if kind in ("short_text", "long_text"):
        if not isinstance(value, str):
            return "not_text"
        limit = getattr(q, "max_length", None) or (500 if kind == "short_text" else 5000)
        return "too_long" if len(value) > limit else None
    if kind in ("number", "rating"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return "not_a_number"
        low, high = getattr(q, "min", None), getattr(q, "max", None)
        if low is not None and value < low:
            return "below_min"
        if high is not None and value > high:
            return "above_max"
        if kind == "rating" and not float(value).is_integer():
            return "not_whole"
        return None
    if kind == "date":
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            return "not_a_date"
        return None
    if kind == "yes_no":
        return None if isinstance(value, bool) else "not_yes_no"
    if kind == "single_choice":
        return None if value in codes else "not_an_option"
    if kind == "multi_choice":
        if not isinstance(value, list) or not value or any(v not in codes for v in value):
            return "not_an_option"
        return "duplicate_choice" if len(set(value)) != len(value) else None
    return "unsupported"


def validate_answers(
    form: FormSchema,
    section_key: str,
    answers: dict[str, Any],
    *,
    complete: bool,
    file_ok: Any = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Check a section's answers. Returns the cleaned answers and any problems.

    Drafts (complete=False) may leave required questions empty. Answers to
    hidden questions are dropped, so they never count. file_ok(ids) says
    whether the given file ids are acceptable attachments.
    """
    section = next((s for s in form.sections if s.key == section_key), None)
    if section is None:
        return {}, [{"where": section_key, "code": "section_unknown"}]
    known = {q.key for q in section.questions}
    problems = [{"where": k, "code": "question_unknown"} for k in answers if k not in known]
    cleaned: dict[str, Any] = {}
    for q in section.questions:
        value = answers.get(q.key)
        # Only accepted answers count, so a hidden question's leftover answer reveals nothing.
        if not _visible(q, cleaned):
            continue
        if _empty(value):
            if complete and q.required:
                problems.append({"where": q.key, "code": "required"})
            continue
        if q.type == "table":
            if not isinstance(value, list) or any(not isinstance(r, dict) for r in value):
                problems.append({"where": q.key, "code": "not_a_table"})
                continue
            if q.max_rows and len(value) > q.max_rows:
                problems.append({"where": q.key, "code": "too_many_rows"})
            rows = []
            for i, row in enumerate(value):
                clean_row = {}
                for col in q.columns:
                    cell = row.get(col.key)
                    if _empty(cell):
                        if complete and col.required:
                            problems.append({"where": f"{q.key}.{i}.{col.key}", "code": "required"})
                        continue
                    problem = _check_scalar(col.type, cell, options=col.options, q=col)
                    if problem:
                        problems.append({"where": f"{q.key}.{i}.{col.key}", "code": problem})
                    clean_row[col.key] = cell
                rows.append(clean_row)
            cleaned[q.key] = rows
            continue
        if q.type == "file":
            if not isinstance(value, list) or any(not isinstance(v, int) for v in value):
                problems.append({"where": q.key, "code": "not_files"})
                continue
            if len(value) > (q.max_files or 5):
                problems.append({"where": q.key, "code": "too_many_files"})
            if file_ok is not None and not file_ok(value):
                problems.append({"where": q.key, "code": "file_not_usable"})
            cleaned[q.key] = value
            continue
        problem = _check_scalar(q.type, value, options=q.options, q=q)
        if problem:
            problems.append({"where": q.key, "code": problem})
        cleaned[q.key] = value
    return cleaned, problems


def section_keys(form: FormSchema, respondent: str) -> list[str]:
    return [s.key for s in form.sections if s.respondent == respondent]


def label(text: Text | dict[str, str], locale: str) -> str:
    if isinstance(text, dict):
        return text.get(locale) or text.get("en") or ""
    return (text.ar if locale == "ar" else text.en) or text.en
