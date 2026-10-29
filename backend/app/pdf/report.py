"""Evaluation reports as PDF, in English or Arabic (FR-E12).

Built from the stored answers on every request, so amendments always show.
One merged Latin and Arabic font with HarfBuzz shaping renders Arabic joined
and right to left, including lines that mix Arabic with codes and dates.
"""

from importlib import resources
from typing import Any

from fpdf import FPDF

from app.forms import schema as form_schema

LABELS = {
    "en": {
        "report": "Ministry report ID",
        "version": "Version ID",
        "evaluation": "Evaluation",
        "school": "School",
        "teacher": "Teacher",
        "supervisor": "Supervisor",
        "visit_date": "Visit date",
        "status": "Status",
        "submitted": "Submitted",
        "amended": "Last amended",
        "notes": "Visit notes",
        "yes": "Yes",
        "no": "No",
        "files": "{n} attachment(s)",
        "page": "Page {n}",
        "statuses": {"draft": "Draft", "submitted": "Submitted", "amended": "Amended", "cancelled": "Cancelled"},
    },
    "ar": {
        "report": "رقم تقرير الوزارة",
        "version": "رقم الإصدار",
        "evaluation": "التقييم",
        "school": "المدرسة",
        "teacher": "المعلم",
        "supervisor": "الموجّه",
        "visit_date": "تاريخ الزيارة",
        "status": "الحالة",
        "submitted": "تاريخ الإرسال",
        "amended": "آخر تعديل",
        "notes": "ملاحظات الزيارة",
        "yes": "نعم",
        "no": "لا",
        "files": "{n} مرفق",
        "page": "صفحة {n}",
        "statuses": {"draft": "مسودة", "submitted": "مُرسل", "amended": "معدّل", "cancelled": "ملغى"},
    },
}


def _date(value: Any) -> str:
    if not value:
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    year, month, day = text[:10].split("-")
    return f"{int(day)}/{month}/{year}"


class _Pdf(FPDF):
    def __init__(self, locale: str, footer_label: str):
        super().__init__(format="A4")
        self.locale = locale
        self.footer_label = footer_label
        fonts = resources.files("app.pdf").joinpath("fonts")
        self.add_font("sces", "", str(fonts.joinpath("SCES-Regular.ttf")))
        self.add_font("sces", "B", str(fonts.joinpath("SCES-Bold.ttf")))
        self.set_text_shaping(use_shaping_engine=True)
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(16, 16, 16)

    @property
    def align(self) -> str:
        return "R" if self.locale == "ar" else "L"

    def line(self, text: str, size: float = 10.5, bold: bool = False, gap: float = 1.5) -> None:
        self.set_font("sces", "B" if bold else "", size)
        self.multi_cell(0, size * 0.55, text, align=self.align, new_x="LMARGIN", new_y="NEXT")
        self.ln(gap)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("sces", "", 8)
        self.cell(0, 6, self.footer_label.format(n=self.page_no()), align="C")


def _answer(q: form_schema.Question, value: Any, locale: str, words: dict[str, Any]) -> str:
    def option_label(options, code):
        match = next((o for o in options if o.code == code), None)
        return form_schema.label(match.label, locale) if match else str(code)

    if q.type == "yes_no":
        return words["yes"] if value else words["no"]
    if q.type == "single_choice":
        return option_label(q.options, value)
    if q.type == "multi_choice":
        return (
            "، ".join(option_label(q.options, v) for v in value)
            if locale == "ar"
            else ", ".join(option_label(q.options, v) for v in value)
        )
    if q.type == "rating":
        return f"{value:g} / {q.max:g}"
    if q.type == "date":
        return _date(value)
    if q.type == "file":
        return words["files"].format(n=len(value))
    if q.type == "table":
        rows = []
        for row in value:
            cells = []
            for c in q.columns:
                if c.key not in row:
                    continue
                cell = row[c.key]
                if c.type == "yes_no":
                    cell = words["yes"] if cell else words["no"]
                elif c.type == "single_choice":
                    cell = option_label(c.options, cell)
                elif c.type == "date":
                    cell = _date(cell)
                cells.append(f"{form_schema.label(c.label, locale)}: {cell}")
            rows.append(" · ".join(cells))
        return "\n".join(rows)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_evaluation(data: dict[str, Any], schema: dict[str, Any], locale: str, district_name: str) -> bytes:
    """data is evaluation_out(...) for the evaluation."""
    words = LABELS["ar" if locale == "ar" else "en"]
    parsed = form_schema.parse(schema)
    pdf = _Pdf(locale, words["page"])
    pdf.add_page()
    report = data["report"]
    pdf.line(district_name, size=9)
    pdf.line(report["title_ar"] if locale == "ar" else report["title_en"], size=16, bold=True, gap=3)
    meta = [
        (words["report"], report["code"]),
        (words["version"], report["version_code"]),
        (words["evaluation"], f"#{data['id']}"),
        (words["school"], f"{data['school']['name']} ({data['school']['code']})"),
    ]
    if data.get("teacher"):
        meta.append((words["teacher"], data["teacher"]["name"]))
    meta += [
        (words["supervisor"], data["supervisor"]["name"]),
        (words["visit_date"], _date(data["visit_date"])),
        (words["status"], words["statuses"].get(data["status"], data["status"])),
        (words["submitted"], _date(data["submitted_at"])),
    ]
    if data.get("amended_at"):
        meta.append((words["amended"], _date(data["amended_at"])))
    for label, value in meta:
        pdf.line(f"{label}: {value}", gap=0.5)
    if data.get("visit_notes"):
        pdf.ln(2)
        pdf.line(words["notes"], bold=True)
        pdf.line(data["visit_notes"])
    answers = {s["key"]: s["answers"] for s in data["sections"]}
    for section in parsed.sections:
        if section.key not in answers:
            continue
        pdf.ln(3)
        pdf.line(form_schema.label(section.title, locale), size=13, bold=True, gap=2)
        given = answers[section.key]
        for q in section.questions:
            if q.key not in given:
                continue
            pdf.line(form_schema.label(q.label, locale), bold=True, gap=0.3)
            pdf.line(_answer(q, given[q.key], locale, words), gap=2)
    return bytes(pdf.output())
