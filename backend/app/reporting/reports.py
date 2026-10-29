"""Standard reports (FR-RP3): evaluation status by school, supervisor and period; request
completion; assignment history; raw answers by form; scanned reports by supervisor, school,
ministry report and period.

Each report starts from the same scope rule as the screens (evaluations, requests and documents
each have one visible_query), so a report never shows more than the user could open. Counts are
done in the database, so they stay quick at design scale. Every report can be filtered by
ministry report ID and version where it applies.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from app import clock
from app.assignments import queries as assignment_queries
from app.auth.deps import Principal
from app.district import get_district
from app.documents import access as documents_access
from app.errors import AppError, invalid, not_found
from app.evaluations import service as evaluations
from app.forms import schema as form_schema
from app.models import (
    Cluster,
    Document,
    Evaluation,
    EvaluationSection,
    FormVersion,
    MinistryReport,
    MinistryReportVersion,
    Role,
    School,
    Supervisor,
    SupervisorAssignment,
    Teacher,
    TeacherRequest,
    User,
)
from app.pdf import report as pdf_report
from app.requests import access as requests_access
from app.requests import service as requests
from app.structure.common import managed_cluster_ids

NAMES = (
    "evaluations_by_school",
    "evaluations_by_supervisor",
    "evaluations_by_period",
    "request_completion",
    "assignment_history",
    "raw_answers",
    "scanned_reports",
)
MAX_ROWS = 20000


class Filters(BaseModel):
    report_id: int | None = None  # ministry report
    report_version_id: int | None = None  # ministry report version
    form_id: int | None = None  # raw answers: one form version
    cluster_id: int | None = None
    school_id: int | None = None
    supervisor_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    group: Literal["supervisor", "school", "report", "period"] = "supervisor"
    q_locale: Literal["en", "ar"] = Field(default="en", exclude=True)


@dataclass
class Column:
    key: str
    en: str
    ar: str

    def label(self, locale: str) -> str:
        return self.ar if locale == "ar" else self.en


@dataclass
class Report:
    name: str
    title_en: str
    title_ar: str
    columns: list[Column]
    rows: list[list[Any]] = field(default_factory=list)

    def title(self, locale: str) -> str:
        return self.title_ar if locale == "ar" else self.title_en


C = Column
SCHOOL_COLS = [
    C("cluster", "Cluster", "المجموعة"),
    C("school_code", "School ID", "رقم المدرسة"),
    C("school", "School", "المدرسة"),
]
EVAL_COUNTS = [
    C("drafts", "Drafts", "مسودات"),
    C("submitted", "Submitted", "مُرسلة"),
    C("amended", "Amended", "معدّلة"),
    C("cancelled", "Cancelled", "ملغاة"),
    C("average_score", "Average score %", "متوسط الدرجة %"),
]


def _round(value: Any) -> float | None:
    return None if value is None else round(float(value), 2)


# Scope and filters --------------------------------------------------------------------------


def _forbid_outsiders(principal: Principal) -> None:
    if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR):
        raise AppError(403, "forbidden")


def _check_filters(db: Session, principal: Principal, f: Filters) -> None:
    # Filters only narrow what the scope already allows, but an unknown id is still worth saying.
    if f.report_version_id and db.get(MinistryReportVersion, f.report_version_id) is None:
        raise invalid("filter_unknown", [{"where": "report_version_id", "code": "unknown"}])
    if f.report_id and db.get(MinistryReport, f.report_id) is None:
        raise invalid("filter_unknown", [{"where": "report_id", "code": "unknown"}])
    if f.date_from and f.date_to and f.date_from > f.date_to:
        raise invalid("filter_dates_reversed")


def _form_ids(f: Filters) -> Select | None:
    """Form versions belonging to the chosen ministry report or version."""
    if f.report_version_id:
        return select(FormVersion.id).where(FormVersion.ministry_report_version_id == f.report_version_id)
    if f.report_id:
        return (
            select(FormVersion.id)
            .join(MinistryReportVersion, MinistryReportVersion.id == FormVersion.ministry_report_version_id)
            .where(MinistryReportVersion.ministry_report_id == f.report_id)
        )
    return None


def _evaluations(db: Session, principal: Principal, f: Filters) -> Select:
    query = evaluations.visible_query(db, principal).join(School, School.id == Evaluation.school_id)
    if (forms := _form_ids(f)) is not None:
        query = query.where(Evaluation.form_version_id.in_(forms))
    if f.cluster_id:
        query = query.where(School.cluster_id == f.cluster_id)
    if f.school_id:
        query = query.where(Evaluation.school_id == f.school_id)
    if f.supervisor_id:
        query = query.where(Evaluation.supervisor_id == f.supervisor_id)
    day = func.coalesce(Evaluation.visit_date, func.date(Evaluation.created_at))
    if f.date_from:
        query = query.where(day >= f.date_from)
    if f.date_to:
        query = query.where(day <= f.date_to)
    return query


def _evaluation_counts() -> list[Any]:
    percent = Evaluation.score["percent"].as_float()
    return [
        func.sum(case((Evaluation.status == "draft", 1), else_=0)),
        func.sum(case((Evaluation.status.in_(("submitted", "amended")), 1), else_=0)),
        func.sum(case((Evaluation.status == "amended", 1), else_=0)),
        func.sum(case((Evaluation.status == "cancelled", 1), else_=0)),
        func.avg(case((Evaluation.status.in_(("submitted", "amended")), percent), else_=None)),
    ]


def _counts_row(values: Any) -> list[Any]:
    drafts, submitted, amended, cancelled, average = values
    return [int(drafts or 0), int(submitted or 0), int(amended or 0), int(cancelled or 0), _round(average)]


# Evaluations ------------------------------------------------------------------------------


def evaluations_by_school(db: Session, principal: Principal, f: Filters) -> Report:
    query = (
        _evaluations(db, principal, f)
        .join(Cluster, Cluster.id == School.cluster_id)
        .with_only_columns(Cluster.code, School.code, School.name, *_evaluation_counts())
        .group_by(Cluster.code, School.code, School.name)
        .order_by(Cluster.code, School.code)
    )
    rows = [[c, code, name, *_counts_row(rest)] for c, code, name, *rest in db.execute(query.limit(MAX_ROWS))]
    return Report(
        "evaluations_by_school",
        "Evaluation status by school",
        "حالة التقييمات حسب المدرسة",
        SCHOOL_COLS + EVAL_COUNTS,
        rows,
    )


def evaluations_by_supervisor(db: Session, principal: Principal, f: Filters) -> Report:
    query = (
        _evaluations(db, principal, f)
        .join(Supervisor, Supervisor.id == Evaluation.supervisor_id)
        .join(User, User.id == Supervisor.user_id)
        .with_only_columns(User.name, User.staff_id, *_evaluation_counts())
        .group_by(User.name, User.staff_id)
        .order_by(User.name)
    )
    rows = [[name, staff, *_counts_row(rest)] for name, staff, *rest in db.execute(query.limit(MAX_ROWS))]
    columns = [C("supervisor", "Supervisor", "الموجّه"), C("staff_id", "Staff ID", "الرقم الوظيفي")] + EVAL_COUNTS
    return Report(
        "evaluations_by_supervisor", "Evaluation status by supervisor", "حالة التقييمات حسب الموجّه", columns, rows
    )


def evaluations_by_period(db: Session, principal: Principal, f: Filters) -> Report:
    month = func.date_format(func.coalesce(Evaluation.visit_date, func.date(Evaluation.created_at)), "%Y-%m")
    query = (
        _evaluations(db, principal, f).with_only_columns(month, *_evaluation_counts()).group_by(month).order_by(month)
    )
    rows = [[period, *_counts_row(rest)] for period, *rest in db.execute(query.limit(MAX_ROWS))]
    return Report(
        "evaluations_by_period",
        "Evaluation status by month",
        "حالة التقييمات حسب الشهر",
        [C("month", "Month", "الشهر")] + EVAL_COUNTS,
        rows,
    )


# Requests and assignments -------------------------------------------------------------------


def request_completion(db: Session, principal: Principal, f: Filters) -> Report:
    query = requests_access.visible_query(db, principal).join(School, School.id == TeacherRequest.school_id)
    query = query.join(Cluster, Cluster.id == School.cluster_id)
    if (forms := _form_ids(f)) is not None:
        query = query.where(TeacherRequest.form_version_id.in_(forms))
    if f.cluster_id:
        query = query.where(School.cluster_id == f.cluster_id)
    if f.school_id:
        query = query.where(TeacherRequest.school_id == f.school_id)
    if f.date_from:
        query = query.where(TeacherRequest.due_date >= f.date_from)
    if f.date_to:
        query = query.where(TeacherRequest.due_date <= f.date_to)
    today = clock.local_date(get_district(db).time_zone)
    is_open = TeacherRequest.status.in_(requests.OPEN)
    query = (
        query.with_only_columns(
            Cluster.code,
            School.code,
            School.name,
            func.count(TeacherRequest.id),
            func.sum(case((TeacherRequest.status == "submitted", 1), else_=0)),
            func.sum(case((TeacherRequest.status == "waived", 1), else_=0)),
            func.sum(case((TeacherRequest.status == "cancelled", 1), else_=0)),
            func.sum(case((is_open, 1), else_=0)),
            func.sum(case((and_(is_open, TeacherRequest.due_date < today), 1), else_=0)),
        )
        .group_by(Cluster.code, School.code, School.name)
        .order_by(Cluster.code, School.code)
    )
    rows = []
    for cluster, code, name, total, submitted, waived, cancelled, open_, overdue in db.execute(query.limit(MAX_ROWS)):
        counted = int(total) - int(cancelled or 0)
        rate = _round(100 * int(submitted or 0) / counted) if counted else None
        rows.append(
            [
                cluster,
                code,
                name,
                int(total),
                int(submitted or 0),
                int(waived or 0),
                int(cancelled or 0),
                int(open_ or 0),
                int(overdue or 0),
                rate,
            ]
        )
    columns = SCHOOL_COLS + [
        C("total", "Requests", "الطلبات"),
        C("submitted", "Submitted", "مُرسلة"),
        C("waived", "Waived", "مُعفاة"),
        C("cancelled", "Cancelled", "ملغاة"),
        C("open", "Open", "مفتوحة"),
        C("overdue", "Overdue", "متأخرة"),
        C("completion", "Completion %", "نسبة الإنجاز %"),
    ]
    return Report("request_completion", "Request completion", "إنجاز الطلبات", columns, rows)


def assignment_history(db: Session, principal: Principal, f: Filters) -> Report:
    query = (
        select(
            Cluster.code,
            School.code,
            School.name,
            User.name,
            User.staff_id,
            SupervisorAssignment.start_date,
            SupervisorAssignment.end_date,
            SupervisorAssignment.reason,
            SupervisorAssignment.end_reason,
        )
        .join(School, School.id == SupervisorAssignment.school_id)
        .join(Cluster, Cluster.id == School.cluster_id)
        .join(Supervisor, Supervisor.id == SupervisorAssignment.supervisor_id)
        .join(User, User.id == Supervisor.user_id)
    )
    if principal.role == Role.SUPERVISOR:
        own = assignment_queries.supervisor_for_user(db, principal.user.id)
        query = query.where(SupervisorAssignment.supervisor_id == (own.id if own else -1))
    elif principal.role == Role.CLUSTER_HEAD:
        query = query.where(School.cluster_id.in_(managed_cluster_ids(db, principal) or []))
    if f.cluster_id:
        query = query.where(School.cluster_id == f.cluster_id)
    if f.school_id:
        query = query.where(SupervisorAssignment.school_id == f.school_id)
    if f.supervisor_id:
        query = query.where(SupervisorAssignment.supervisor_id == f.supervisor_id)
    # Assignments that overlap the period.
    if f.date_to:
        query = query.where(SupervisorAssignment.start_date <= f.date_to)
    if f.date_from:
        query = query.where(or_(SupervisorAssignment.end_date.is_(None), SupervisorAssignment.end_date >= f.date_from))
    query = query.order_by(Cluster.code, School.code, SupervisorAssignment.start_date)
    rows = [list(r) for r in db.execute(query.limit(MAX_ROWS))]
    columns = SCHOOL_COLS + [
        C("supervisor", "Supervisor", "الموجّه"),
        C("staff_id", "Staff ID", "الرقم الوظيفي"),
        C("start", "From", "من"),
        C("end", "To", "إلى"),
        C("reason", "Reason", "السبب"),
        C("end_reason", "End reason", "سبب الانتهاء"),
    ]
    return Report("assignment_history", "Assignment history", "سجل الإسناد", columns, rows)


# Raw answers --------------------------------------------------------------------------------


def raw_answers(db: Session, principal: Principal, f: Filters) -> Report:
    if not f.form_id:
        raise invalid("form_required", [{"where": "form_id", "code": "required"}])
    form = db.get(FormVersion, f.form_id)
    if form is None:
        raise not_found()
    parsed = form_schema.parse(form.schema)
    mrv = db.get(MinistryReportVersion, form.ministry_report_version_id)
    report = db.get(MinistryReport, mrv.ministry_report_id)
    locale = f.q_locale
    words = pdf_report.LABELS[locale]
    questions = [(s, q) for s in parsed.sections for q in s.questions]
    columns = [
        C("evaluation", "Evaluation", "التقييم"),
        C("report", "Ministry report ID", "رقم تقرير الوزارة"),
        C("version", "Version ID", "رقم الإصدار"),
        *SCHOOL_COLS[1:],
        C("teacher", "Teacher", "المعلم"),
        C("supervisor", "Supervisor", "الموجّه"),
        C("visit_date", "Visit date", "تاريخ الزيارة"),
        C("status", "Status", "الحالة"),
        C("points", "Score", "الدرجة"),
        C("percent", "Score %", "الدرجة %"),
        C("band", "Band", "الفئة"),
    ] + [C(f"{s.key}.{q.key}", q.label.en or q.key, q.label.ar or q.label.en or q.key) for s, q in questions]
    query = (
        _evaluations(db, principal, Filters(**{**f.model_dump(), "report_id": None, "report_version_id": None}))
        .where(Evaluation.form_version_id == f.form_id, Evaluation.status != "cancelled")
        .order_by(Evaluation.id)
        .limit(MAX_ROWS)
    )
    rows = []
    for e in db.execute(query).scalars():
        answers = {
            s.section_key: s.answers
            for s in db.execute(select(EvaluationSection).where(EvaluationSection.evaluation_id == e.id)).scalars()
        }
        for part in requests.evaluation_sections(db, e):
            answers[part["key"]] = part["answers"]
        school = db.get(School, e.school_id)
        teacher = db.get(User, db.get(Teacher, e.teacher_id).user_id).name if e.teacher_id else ""
        supervisor = db.get(User, db.get(Supervisor, e.supervisor_id).user_id).name
        score = e.score or {}
        band = score.get("band") or {}
        row = [
            e.id,
            report.report_code,
            mrv.version_code,
            school.code,
            school.name,
            teacher,
            supervisor,
            e.visit_date,
            words["statuses"].get(e.status, e.status),
            score.get("points"),
            score.get("percent"),
            band.get(locale) or band.get("en") or "",
        ]
        for s, q in questions:
            value = (answers.get(s.key) or {}).get(q.key)
            row.append("" if value is None else pdf_report._answer(q, value, locale, words))
        rows.append(row)
    return Report(
        "raw_answers",
        f"Answers: {report.report_code} {mrv.version_code}",
        f"الإجابات: {report.report_code} {mrv.version_code}",
        columns,
        rows,
    )


# Scanned reports ----------------------------------------------------------------------------


def scanned_reports(db: Session, principal: Principal, f: Filters) -> Report:
    query = documents_access.visible_query(db, principal).join(School, School.id == Document.school_id)
    query = query.join(MinistryReportVersion, MinistryReportVersion.id == Document.ministry_report_version_id)
    query = query.join(MinistryReport, MinistryReport.id == MinistryReportVersion.ministry_report_id)
    if f.report_version_id:
        query = query.where(Document.ministry_report_version_id == f.report_version_id)
    if f.report_id:
        query = query.where(MinistryReport.id == f.report_id)
    if f.cluster_id:
        query = query.where(Document.cluster_id == f.cluster_id)
    if f.school_id:
        query = query.where(Document.school_id == f.school_id)
    if f.supervisor_id:
        query = query.where(Document.owner_supervisor_id == f.supervisor_id)
    if f.date_from:
        query = query.where(Document.report_date >= f.date_from)
    if f.date_to:
        query = query.where(Document.report_date <= f.date_to)
    if f.group == "supervisor":
        query = query.join(Supervisor, Supervisor.id == Document.owner_supervisor_id).join(
            User, User.id == Supervisor.user_id
        )
        keys = [User.name, User.staff_id]
        key_cols = [C("supervisor", "Supervisor", "الموجّه"), C("staff_id", "Staff ID", "الرقم الوظيفي")]
    elif f.group == "school":
        keys = [School.code, School.name]
        key_cols = SCHOOL_COLS[1:]
    elif f.group == "report":
        keys = [MinistryReport.report_code, MinistryReportVersion.version_code]
        key_cols = [C("report", "Ministry report ID", "رقم تقرير الوزارة"), C("version", "Version ID", "رقم الإصدار")]
    else:
        keys = [func.date_format(Document.report_date, "%Y-%m")]
        key_cols = [C("month", "Month", "الشهر")]
    status = Document.status
    deleted = Document.deleted_at.is_not(None)
    counts = [
        func.count(Document.id),
        func.sum(case((and_(status == "draft", ~deleted), 1), else_=0)),
        func.sum(case((and_(status.in_(("submitted", "viewed")), ~deleted), 1), else_=0)),
        func.sum(case((and_(status == "acknowledged", ~deleted), 1), else_=0)),
        func.sum(case((and_(status == "returned", ~deleted), 1), else_=0)),
        func.sum(case((deleted, 1), else_=0)) if principal.role == Role.DISTRICT_ADMIN else literal(0),
    ]
    query = query.with_only_columns(*keys, *counts).group_by(*keys).order_by(*keys)
    width = len(keys)
    rows = [[*r[:width], *(int(v or 0) for v in r[width:])] for r in db.execute(query.limit(MAX_ROWS))]
    columns = key_cols + [
        C("total", "Reports", "التقارير"),
        C("drafts", "Drafts", "مسودات"),
        C("in_review", "Awaiting review", "بانتظار المراجعة"),
        C("acknowledged", "Acknowledged", "تم الاستلام"),
        C("returned", "Returned", "مُعادة"),
        C("deleted", "Deleted", "محذوفة"),
    ]
    titles = {
        "supervisor": ("Scanned reports by supervisor", "التقارير الممسوحة حسب الموجّه"),
        "school": ("Scanned reports by school", "التقارير الممسوحة حسب المدرسة"),
        "report": ("Scanned reports by ministry report", "التقارير الممسوحة حسب تقرير الوزارة"),
        "period": ("Scanned reports by month", "التقارير الممسوحة حسب الشهر"),
    }[f.group]
    return Report("scanned_reports", *titles, columns, rows)


BUILDERS = {
    "evaluations_by_school": evaluations_by_school,
    "evaluations_by_supervisor": evaluations_by_supervisor,
    "evaluations_by_period": evaluations_by_period,
    "request_completion": request_completion,
    "assignment_history": assignment_history,
    "raw_answers": raw_answers,
    "scanned_reports": scanned_reports,
}


def build(db: Session, principal: Principal, name: str, f: Filters) -> Report:
    _forbid_outsiders(principal)
    if name not in BUILDERS:
        raise not_found()
    _check_filters(db, principal, f)
    return BUILDERS[name](db, principal, f)
