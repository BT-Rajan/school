"""Phase 2 security review (delivery plan, Phase 2 exit criteria): ID guessing, link reuse
and upload attacks against document, evaluation, form and file endpoints.

Findings and fixes are recorded in docs/security-review-phase2.md.
"""

from datetime import timedelta

from sqlalchemy import select

from app.db import session_factory
from app.models import DocumentVersion

from .test_documents import TODAY, act, create, scan, submitted, upload, w  # noqa: F401
from .test_evaluations import GOOD
from .test_files import pdf_bytes


def stored_file_id(document_id: int) -> int:
    with session_factory()() as db:
        return db.execute(
            select(DocumentVersion.stored_file_id).where(DocumentVersion.document_id == document_id)
        ).scalar_one()


# ID guessing ----------------------------------------------------------------------------------


def test_guessed_ids_reveal_nothing(w):
    """Out-of-scope and missing records answer alike: 404, never 403 with details."""
    doc = submitted(w)
    file_id = stored_file_id(doc["id"])
    for client in (w["b"], w["teacher_client"], w["author"], w["head"]):
        for path in (
            f"/api/documents/{doc['id']}",
            f"/api/documents/{doc['id'] + 1000}",
            f"/api/files/{file_id}",
            f"/api/documents/{doc['id']}/access",
        ):
            r = client.get(path)
            assert r.status_code in (403, 404), (path, r.status_code)
            assert "School" not in r.text and "scan" not in r.text
        assert client.post(f"/api/documents/{doc['id']}/link", json={}).status_code in (403, 404)
        assert client.post(f"/api/files/{file_id}/link", json={}).status_code in (403, 404)


def test_evaluation_ids_reveal_nothing(w):
    a = w["a"]
    e = a.post("/api/evaluations", json={"form_id": w["form_id"], "school_id": w["school_x"].id}).json()
    for client in (w["b"], w["teacher_client"], w["author"], w["other_head"]):
        assert client.get(f"/api/evaluations/{e['id']}").status_code in (403, 404)
        assert client.get(f"/api/evaluations/{e['id']}/pdf").status_code in (403, 404)
        assert client.get(f"/api/evaluations/{e['id']}/documents").status_code in (403, 404)
        r = client.patch(f"/api/evaluations/{e['id']}", json={"version": e["version"], "sections": {"visit": GOOD}})
        assert r.status_code in (403, 404)


def test_draft_forms_are_hidden_from_field_staff(w):
    draft = w["author"].post("/api/catalog/reports", json={"report_code": "HIDDEN-1", "subject_type": "school"})
    assert draft.status_code == 201
    form = w["author"].post(f"/api/catalog/reports/{draft.json()['id']}/versions", json={"version_code": "1"}).json()
    for client in (w["a"], w["head"], w["teacher_client"]):
        assert client.get(f"/api/forms/{form['id']}").status_code in (403, 404)
        assert client.get(f"/api/forms/{form['id']}/comments").status_code in (403, 404)
        assert client.patch(f"/api/forms/{form['id']}", json={"version": 1, "schema": {}}).status_code in (403, 404)
        assert "HIDDEN-1" not in client.get("/api/catalog").text


# Link reuse -------------------------------------------------------------------------------------


def test_document_files_open_only_through_the_document(w):
    """A direct file link would skip view tracking and the owner's access history (FR-D21, FR-L9)."""
    doc = submitted(w)
    scan()
    file_id = stored_file_id(doc["id"])
    for client in (w["admin1"], w["a"]):
        assert client.post(f"/api/files/{file_id}/link", json={"disposition": "inline"}).status_code == 404
    # The document's own link still works, and the admin's view is recorded for the owner.
    url = w["admin1"].post(f"/api/documents/{doc['id']}/link", json={}).json()["url"]
    assert w["admin1"].get(url).status_code == 200
    history = w["a"].get(f"/api/documents/{doc['id']}/access").json()
    assert [h["action"] for h in history] == ["viewed"]


def test_a_shared_link_stops_working_when_sharing_is_revoked(w):
    doc = submitted(w)
    scan()
    w["admin1"].post(f"/api/documents/{doc['id']}/forward", json={})
    url = w["head"].post(f"/api/documents/{doc['id']}/link", json={}).json()["url"]
    w["admin1"].post(f"/api/documents/{doc['id']}/revoke-forward")
    # Access is checked again when the file is fetched, not only when the link was made.
    assert w["head"].get(url).status_code == 404


def test_a_deleted_report_link_stops_working(w):
    r = create(w["a"], w)
    doc = r.json()
    scan()
    url = w["a"].post(f"/api/documents/{doc['id']}/link", json={}).json()["url"]
    assert act(w["a"], doc, "delete").status_code == 200
    assert w["a"].get(url).status_code == 404


def test_cluster_head_cannot_read_access_history(w):
    doc = submitted(w)
    w["admin1"].post(f"/api/documents/{doc['id']}/forward", json={})
    assert w["head"].get(f"/api/documents/{doc['id']}").status_code == 200
    assert w["head"].get(f"/api/documents/{doc['id']}/access").status_code == 403


# Upload and input attacks -----------------------------------------------------------------------


def test_others_uploads_and_used_files_cannot_be_claimed(w):
    b_file = upload(w["b"])
    r = create(w["a"], w, file_ids=[b_file])
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_not_usable"
    # A file already inside one report cannot be reused for another.
    doc = submitted(w)
    r = create(w["a"], w, file_ids=[stored_file_id(doc["id"])])
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_not_usable"


def test_oversized_requests_are_refused_before_they_are_read(w):
    big = b"0" * (3 * 1024 * 1024)
    r = w["a"].post("/api/documents", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    r = w["a"].post(
        "/api/files",
        content=b"x" * 10,
        headers={"Content-Type": "multipart/form-data; boundary=x", "Content-Length": str(200 * 1024 * 1024)},
    )
    assert r.status_code == 413


def test_unbounded_answers_and_search_are_refused(w):
    a = w["a"]
    e = a.post("/api/evaluations", json={"form_id": w["form_id"], "school_id": w["school_x"].id}).json()
    rows = [{"name": "x", "present": True}] * 201
    r = a.patch(f"/api/evaluations/{e['id']}", json={"version": e["version"], "sections": {"visit": {"staff": rows}}})
    assert r.status_code == 422
    assert a.get("/api/documents", params={"q": "x" * 101}).status_code == 422


def test_oversized_form_definitions_are_refused(w):
    report = w["author"].post("/api/catalog/reports", json={"report_code": "BIG-1", "subject_type": "school"}).json()
    form = w["author"].post(f"/api/catalog/reports/{report['id']}/versions", json={"version_code": "1"}).json()
    question = {"key": "q", "type": "single_choice", "label": {"en": "Q", "ar": "س"}}
    options = [{"code": f"o{i}", "label": {"en": "o", "ar": "o"}} for i in range(501)]
    section = {"key": "s", "title": {"en": "S"}, "respondent": "supervisor"}
    schema = {"sections": [{**section, "questions": [{**question, "options": options}]}]}
    r = w["author"].patch(f"/api/forms/{form['id']}", json={"version": form["version"], "schema": schema})
    assert r.status_code == 422


def test_report_dates_cannot_be_used_to_reach_before_an_assignment(w):
    r = create(w["a"], w, report_date=str(TODAY - timedelta(days=400)))
    assert r.status_code == 422 and r.json()["error"]["code"] == "report_date_outside_assignment"


def test_disguised_and_active_uploads(w):
    a = w["a"]
    html = b"<html><script>alert(1)</script></html>"
    r = a.post("/api/files", files={"file": ("scan.pdf", html)})
    assert r.status_code == 422
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert a.post("/api/files", files={"file": ("scan.svg", svg)}).status_code == 422
    # A PDF with JavaScript is accepted only after the script is removed.
    r = a.post("/api/files", files={"file": ("scan.pdf", pdf_bytes(javascript=True))})
    assert r.status_code == 201
    # Path and header tricks in the name are kept as text, never used as a path or header.
    r = a.post("/api/files", files={"file": ('../../etc/x"\r\nX-Evil: 1.pdf', pdf_bytes())})
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        scan()
        url = a.post(f"/api/files/{r.json()['id']}/link", json={}).json()["url"]
        served = a.get(url)
        assert "x-evil" not in served.headers


def test_a_body_without_a_declared_length_is_cut_off_at_the_limit():
    import asyncio

    import pytest

    from app.body_limit import BodyLimitMiddleware
    from app.errors import AppError

    async def app(scope, receive, send):
        while (await receive()).get("more_body"):
            pass

    chunk = b"x" * (1024 * 1024)

    async def receive():
        return {"type": "http.request", "body": chunk, "more_body": True}

    scope = {"type": "http", "method": "POST", "path": "/api/documents", "headers": []}
    with pytest.raises(AppError) as error:
        asyncio.run(BodyLimitMiddleware(app)(scope, receive, None))
    assert error.value.status == 413
