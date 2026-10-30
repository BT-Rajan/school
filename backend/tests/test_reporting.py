import io
import zipfile

import pikepdf
from openpyxl import load_workbook
from sqlalchemy import select

from app import jobs
from app.db import session_factory
from app.models import AuditLog
from app.reporting import archive

from .test_documents import TODAY, act, scan, submitted, w  # noqa: F401 - w is the shared fixture


def evaluation(w, client, *, submit: bool):
    e = client.post(
        "/api/evaluations", json={"form_id": w["form_id"], "school_id": w["school_x"].id, "visit_date": str(TODAY)}
    ).json()
    answers = {"met_principal": True, "classrooms": 4, "rating": 3, "staff": [{"name": "Ali"}]}
    e = client.patch(
        f"/api/evaluations/{e['id']}", json={"version": e["version"], "sections": {"visit": answers}}
    ).json()
    if submit:
        e = client.post(f"/api/evaluations/{e['id']}/submit", json={"version": e["version"]}).json()
    return e


def rows(client, name, **params):
    r = client.get(f"/api/standard-reports/{name}", params=params)
    assert r.status_code == 200, r.text
    return r.json()["rows"]


def test_reports_show_only_what_the_user_may_see(w):
    evaluation(w, w["a"], submit=True)
    evaluation(w, w["b"], submit=False)
    # Admin: the whole school, by school; drafts, submitted, amended, cancelled, average score.
    assert rows(w["admin1"], "evaluations_by_school") == [["C1", "SX", "School SX", 1, 1, 0, 0, None]]
    # A supervisor sees their own work only.
    assert [r[0] for r in rows(w["a"], "evaluations_by_supervisor")] == ["a"]
    assert rows(w["b"], "evaluations_by_school")[0][3:5] == [1, 0]
    # The Cluster Head of another cluster sees nothing of this one.
    assert rows(w["other_head"], "evaluations_by_school") == []
    assert len(rows(w["head"], "evaluations_by_period")) == 1
    # Teachers and Form Authors have no reports.
    for outsider in (w["teacher_client"], w["author"]):
        assert outsider.get("/api/standard-reports/evaluations_by_school").status_code == 403
    assert w["admin1"].get("/api/standard-reports/nope").status_code == 404


def test_report_filters_by_ministry_report_and_version(w):
    evaluation(w, w["a"], submit=True)
    assert len(rows(w["admin1"], "evaluations_by_school", report_version_id=w["mrv"])) == 1
    with session_factory()() as db:
        from app.models import MinistryReportVersion

        report_id = db.get(MinistryReportVersion, w["mrv"]).ministry_report_id
    assert len(rows(w["admin1"], "evaluations_by_school", report_id=report_id)) == 1
    r = w["admin1"].get("/api/standard-reports/evaluations_by_school", params={"report_version_id": 9999})
    assert r.json()["error"]["code"] == "filter_unknown"
    r = w["admin1"].get(
        "/api/standard-reports/evaluations_by_school", params={"date_from": "2026-11-10", "date_to": "2026-11-01"}
    )
    assert r.json()["error"]["code"] == "filter_dates_reversed"


def test_scanned_reports_follow_document_isolation(w):
    doc = submitted(w)
    assert rows(w["admin1"], "scanned_reports", group="school") == [["SX", "School SX", 1, 0, 1, 0, 0, 0]]
    # The second supervisor on the same school, and a Cluster Head before a forward: nothing.
    assert rows(w["b"], "scanned_reports", group="school") == []
    assert rows(w["head"], "scanned_reports", group="report") == []
    act(w["admin1"], w["admin1"].get(f"/api/documents/{doc['id']}").json(), "forward", note="For you")
    assert rows(w["head"], "scanned_reports", group="report")[0][:3] == ["MOE-SV-01", "2026.1", 1]
    assert rows(w["a"], "scanned_reports", group="period")[0][1] == 1


def test_exports_are_audited_in_both_languages(w):
    evaluation(w, w["a"], submit=True)
    admin = w["admin1"]
    r = admin.get(
        "/api/standard-reports/evaluations_by_school",
        params={"format": "xlsx", "locale": "ar", "school_id": w["school_x"].id},
    )
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    sheet = load_workbook(io.BytesIO(r.content)).active
    assert sheet.sheet_view.rightToLeft is True
    assert sheet["A1"].value == "حالة التقييمات حسب المدرسة"
    assert "SX" in sheet["A2"].value  # the filter, by name
    assert [c.value for c in sheet[6]][:3] == ["المجمع", "رقم المدرسة", "المدرسة"]
    assert [c.value for c in sheet[7]][:3] == ["C1", "SX", "School SX"]
    for locale in ("en", "ar"):
        r = admin.get("/api/standard-reports/assignment_history", params={"format": "pdf", "locale": locale})
        assert r.status_code == 200 and r.content.startswith(b"%PDF-")
        with pikepdf.open(io.BytesIO(r.content)) as pdf:
            assert len(pdf.pages) >= 1
    with session_factory()() as db:
        exported = (
            db.execute(select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.seq))
            .scalars()
            .all()
        )
    assert [e.entity_id for e in exported] == ["evaluations_by_school", "assignment_history", "assignment_history"]
    assert exported[0].after["rows"] == 1 and exported[0].after["filters"]["school_id"] == w["school_x"].id
    # Viewing on screen is not an export.
    rows(admin, "evaluations_by_school")
    with session_factory()() as db:
        assert len(db.execute(select(AuditLog).where(AuditLog.action == "report.exported")).all()) == 3


def test_raw_answers_by_form(w):
    evaluation(w, w["a"], submit=True)
    admin = w["admin1"]
    assert admin.get("/api/standard-reports/raw_answers").json()["error"]["code"] == "form_required"
    report = admin.get("/api/standard-reports/raw_answers", params={"form_id": w["form_id"]}).json()
    keys = [c["key"] for c in report["columns"]]
    assert keys[:3] == ["evaluation", "report", "version"] and "visit.met_principal" in keys
    row = dict(zip(keys, report["rows"][0], strict=True))
    assert (row["report"], row["version"], row["visit.met_principal"], row["visit.classrooms"]) == (
        "MOE-SV-01",
        "2026.1",
        "Yes",
        "4",
    )
    ar = admin.get("/api/standard-reports/raw_answers", params={"form_id": w["form_id"], "locale": "ar"}).json()
    assert dict(zip(keys, ar["rows"][0], strict=True))["visit.met_principal"] == "نعم"
    # Another supervisor's answers stay out of their own export.
    assert w["b"].get("/api/standard-reports/raw_answers", params={"form_id": w["form_id"]}).json()["rows"] == []


def test_search_within_scope(w):
    submitted(w)
    evaluation(w, w["a"], submit=True)
    found = w["admin1"].get("/api/search", params={"q": "SX"}).json()
    assert found["schools"]["total"] == 1 and found["evaluations"]["total"] == 1
    assert set(found) == {"schools", "teachers", "supervisors", "evaluations", "documents"}
    # The other supervisor finds the school but none of A's work.
    other = w["b"].get("/api/search", params={"q": "School"}).json()
    assert other["evaluations"]["total"] == 0 and other["documents"]["total"] == 0 and "supervisors" not in other
    mine = w["a"].get("/api/search", params={"q": "School"}).json()
    assert mine["evaluations"]["total"] == 1
    assert w["teacher_client"].get("/api/search", params={"q": "School"}).status_code == 403
    with session_factory()() as db:
        assert not db.execute(select(AuditLog).where(AuditLog.action.like("%.access"))).first()


def test_dashboards_by_role(w):
    submitted(w)
    evaluation(w, w["a"], submit=False)
    admin = w["admin1"].get("/api/dashboard").json()
    assert admin["counts"]["schools"] == 2 and admin["inbox"]["submitted"] == 1
    assert admin["coverage"][0]["with_report"] == 1 and admin["coverage"][0]["report"]["code"] == "MOE-SV-01"
    assert admin["audit"] is None and admin["quarantined"] == 0 and admin["storage"]["files"] >= 1
    head = w["head"].get("/api/dashboard").json()
    assert head["unassigned_schools"] == [] and {s["code"] for s in head["without_contact"]} == {"SX", "SY"}
    assert [(p["code"], p["drafts"]) for p in head["progress"]] == [("SX", 1), ("SY", 0)]
    assert {x["name"]: x["schools"] for x in head["workload"]} == {"a": 2, "b": 1}
    sup = w["a"].get("/api/dashboard").json()
    assert sup["draft_count"] == 1 and len(sup["upcoming"]) == 1 and sup["reports"] == {"submitted": 1}
    assert w["teacher_client"].get("/api/dashboard").json() == {"role": "teacher", "pending": [], "pending_count": 0}
    assert w["author"].get("/api/dashboard").status_code == 403


def test_zip_export_of_reports(w, monkeypatch):
    first, second = submitted(w), submitted(w)
    scan()
    admin = w["admin1"]
    assert w["a"].post("/api/document-exports", json={}).status_code == 403
    monkeypatch.setattr(archive, "MAX_DOCUMENTS", 1)
    assert admin.post("/api/document-exports", json={}).json()["error"]["code"] == "export_too_many"
    monkeypatch.setattr(archive, "MAX_DOCUMENTS", 200)
    assert (
        admin.post("/api/document-exports", json={"school_id": w["school_y"].id}).json()["error"]["code"]
        == "export_empty"
    )
    job = admin.post("/api/document-exports", json={"school_id": w["school_x"].id})
    assert job.status_code == 202 and job.json()["status"] == "queued" and job.json()["count"] == 2
    with session_factory()() as db:
        assert jobs.run_next(db)
    scan()
    done = admin.get("/api/document-exports").json()[0]
    assert done["status"] == "done" and done["count"] == 2 and done["file"]["status"] == "clean"
    link = admin.post(f"/api/files/{done['file']['id']}/link", json={"disposition": "attachment"}).json()
    content = admin.get(link["url"]).content
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = sorted(z.namelist())
        assert names[-1] == "manifest.csv" and len(names) == 3
        manifest = z.read("manifest.csv").decode("utf-8-sig")
        assert str(first["id"]) in manifest and str(second["id"]) in manifest
        with pikepdf.open(io.BytesIO(z.read(names[0]))) as pdf:
            # The watermark is an overlay on each page.
            assert len(pdf.pages) == 2
    # Only the admin who asked can download it.
    assert (
        w["admin2"].post(f"/api/files/{done['file']['id']}/link", json={"disposition": "attachment"}).status_code == 404
    )
    with session_factory()() as db:
        exported = db.execute(select(AuditLog).where(AuditLog.action == "documents.exported")).scalar_one()
        requested = db.execute(select(AuditLog).where(AuditLog.action == "documents.export_requested")).scalar_one()
    assert sorted(exported.after["document_ids"]) == sorted([first["id"], second["id"]])
    assert len(requested.after["document_ids"]) == 2
