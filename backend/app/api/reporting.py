from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.deps import Principal, current_principal
from app.db import get_db
from app.district import get_district
from app.models import Cluster, FormVersion, MinistryReport, MinistryReportVersion, School, Supervisor, User
from app.reporting import archive, dashboards, render, reports, search
from app.reporting.archive import ZipIn

router = APIRouter(prefix="/api", tags=["reporting"])

MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.get("/search")
def global_search(
    q: str = Query(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    return search.search(db, principal, q)


@router.get("/dashboard")
def dashboard(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return dashboards.dashboard(db, principal)


def _filter_names(db: Session, f: reports.Filters, locale: str) -> dict[str, str]:
    """What the filters mean, for the export's heading."""
    names: dict[str, str] = {}
    if f.report_id and (r := db.get(MinistryReport, f.report_id)):
        names["report_id"] = r.report_code
    if f.report_version_id and (v := db.get(MinistryReportVersion, f.report_version_id)):
        names["report_version_id"] = f"{db.get(MinistryReport, v.ministry_report_id).report_code} {v.version_code}"
    if f.form_id and (form := db.get(FormVersion, f.form_id)):
        v = db.get(MinistryReportVersion, form.ministry_report_version_id)
        names["form_id"] = f"{db.get(MinistryReport, v.ministry_report_id).report_code} {v.version_code}"
    if f.cluster_id and (c := db.get(Cluster, f.cluster_id)):
        names["cluster_id"] = f"{c.code} · {c.name}"
    if f.school_id and (s := db.get(School, f.school_id)):
        names["school_id"] = f"{s.code} · {s.name}"
    if f.supervisor_id and (sup := db.get(Supervisor, f.supervisor_id)):
        names["supervisor_id"] = db.get(User, sup.user_id).name
    return names


@router.get("/standard-reports/{name}")
def standard_report(
    name: str,
    format: Literal["json", "xlsx", "pdf"] = "json",
    locale: Literal["en", "ar"] = "en",
    filters: reports.Filters = Depends(),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    filters.q_locale = locale
    report = reports.build(db, principal, name, filters)
    if format == "json":
        return render.to_json(report, locale)
    district = get_district(db)
    shown = filters.model_dump(mode="json")
    text = render.filter_text(shown, _filter_names(db, filters, locale), locale)
    made = render.WORDS[locale]["made"].format(name=principal.user.name, at=render.stamp(district.time_zone))
    if format == "xlsx":
        body = render.to_xlsx(report, locale, text, made)
    else:
        body = render.to_pdf(report, locale, text, made, district.name_ar if locale == "ar" else district.name_en)
    # FR-RP4: every export, with who asked, the parameters and the row count.
    audit.record(
        db,
        "report.exported",
        entity_type="report",
        entity_id=name,
        after={
            "format": format,
            "locale": locale,
            "filters": {k: v for k, v in shown.items() if v is not None},
            "rows": len(report.rows),
        },
    )
    db.commit()
    filename = f"{name}-{locale}.{format}"
    return Response(
        body, media_type=MEDIA[format], headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/document-exports", status_code=202)
def request_zip(body: ZipIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return archive.job_out(db, archive.request_zip(db, principal, body))


@router.get("/document-exports")
def my_zip_exports(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return archive.my_exports(db, principal)
