"""Reports as screen data, Excel and PDF, in English or Arabic (FR-RP3, FR-RP4).

Exports carry the report's title, its filters, who made it and when. Arabic exports read right
to left: the sheet is mirrored in Excel, and the PDF's columns run from the right with the
same embedded fonts as evaluation PDFs (FR-I7).
"""

import io
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fpdf.fonts import FontFace
from openpyxl import Workbook
from openpyxl.styles import Font

from app.pdf import report as pdf_report

from .reports import Report

FILTER_LABELS = {
    "report_id": ("Ministry report", "تقرير الوزارة"),
    "report_version_id": ("Ministry report version", "إصدار تقرير الوزارة"),
    "form_id": ("Form", "النموذج"),
    "cluster_id": ("Cluster", "المجموعة"),
    "school_id": ("School", "المدرسة"),
    "supervisor_id": ("Supervisor", "الموجّه"),
    "date_from": ("From", "من"),
    "date_to": ("To", "إلى"),
    "group": ("Grouped by", "التجميع حسب"),
    "actor_id": ("Actor ID", "رقم المنفّذ"),
    "action": ("Action", "الإجراء"),
    "entity_type": ("Entity", "الكيان"),
    "entity_id": ("Entity ID", "رقم الكيان"),
    "severity": ("Severity", "الأهمية"),
}
WORDS = {
    "en": {
        "made": "Made by {name} on {at}",
        "rows": "Rows: {n}",
        "filters": "Filters",
        "none": "None",
        "page": "Page {n}",
    },
    "ar": {
        "made": "أعدّه {name} في {at}",
        "rows": "عدد الصفوف: {n}",
        "filters": "عوامل التصفية",
        "none": "لا يوجد",
        "page": "صفحة {n}",
    },
}


def cell(value: Any) -> Any:
    if isinstance(value, date):
        return pdf_report._date(value)
    return "" if value is None else value


def filter_text(filters: dict[str, Any], names: dict[str, str], locale: str) -> str:
    parts = []
    for key, value in filters.items():
        if value in (None, "") or key not in FILTER_LABELS:
            continue
        label = FILTER_LABELS[key][1 if locale == "ar" else 0]
        parts.append(f"{label}: {names.get(key) or cell(value)}")
    return " · ".join(parts) or WORDS[locale]["none"]


def stamp(time_zone: str) -> str:
    local = datetime.now(UTC).astimezone(ZoneInfo(time_zone))
    return f"{local.day}/{local.month:02d}/{local.year} {local.hour:02d}:{local.minute:02d}"


def to_json(report: Report, locale: str) -> dict[str, Any]:
    return {
        "name": report.name,
        "title": report.title(locale),
        "columns": [{"key": c.key, "label": c.label(locale)} for c in report.columns],
        "rows": report.rows,
    }


def to_xlsx(report: Report, locale: str, filters: str, made: str) -> bytes:
    words = WORDS[locale]
    book = Workbook()
    sheet = book.active
    sheet.title = report.name[:31]
    sheet.sheet_view.rightToLeft = locale == "ar"
    sheet.append([report.title(locale)])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet.append([f"{words['filters']}: {filters}"])
    sheet.append([made])
    sheet.append([words["rows"].format(n=len(report.rows))])
    sheet.append([])
    sheet.append([c.label(locale) for c in report.columns])
    for c in sheet[sheet.max_row]:
        c.font = Font(bold=True)
    for row in report.rows:
        # Dates stay real dates in Excel; everything else as given.
        sheet.append([v if isinstance(v, int | float | date) or v is None else str(v) for v in row])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def to_pdf(report: Report, locale: str, filters: str, made: str, district_name: str) -> bytes:
    words = WORDS[locale]
    pdf = pdf_report._Pdf(locale, words["page"], orientation="L")
    pdf.add_page()
    pdf.line(district_name, size=9)
    pdf.line(report.title(locale), size=15, bold=True, gap=2)
    pdf.line(f"{words['filters']}: {filters}", size=9, gap=0.5)
    pdf.line(made, size=9, gap=0.5)
    pdf.line(words["rows"].format(n=len(report.rows)), size=9, gap=3)
    columns = [c.label(locale) for c in report.columns]
    rows = [[str(cell(v)) for v in r] for r in report.rows]
    if locale == "ar":
        # Right to left: the first column is on the right.
        columns = columns[::-1]
        rows = [r[::-1] for r in rows]
    size = 8 if len(columns) <= 10 else 6.5
    pdf.set_font("sces", "", size)
    align = "RIGHT" if locale == "ar" else "LEFT"
    heads = FontFace(family="sces", emphasis="BOLD", fill_color=(238, 241, 245))
    with pdf.table(text_align=align, line_height=size * 0.6, first_row_as_headings=True, headings_style=heads) as table:
        heading = table.row()
        for label in columns:
            heading.cell(label)
        for r in rows:
            row = table.row()
            for value in r:
                row.cell(value)
    return bytes(pdf.output())
