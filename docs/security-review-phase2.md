# Phase 2 security review: documents, forms, evaluations, files

Date: 29 October 2026. Scope: the endpoints added in Phase 2 under `/api/documents`,
`/api/evaluations`, `/api/forms`, `/api/catalog` and `/api/files`, the web server
configuration in front of them, and the screens that call them. The Phase 2 exit
criterion is "no open high findings". None are open.

## Method

- Read the access rules and every code path that returns a record or a file:
  `app/documents/access.py`, `app/documents/service.py`, `app/files/service.py`,
  `app/forms/service.py`, `app/evaluations/service.py`.
- Wrote attacks as tests, so they keep running in CI:
  `backend/tests/test_security_phase2.py`, alongside the existing isolation tests in
  `test_documents.py`, `test_files.py` and `test_evaluations.py` and the permission
  matrix in `test_structure.py`.
- Drove every role through the screens with the browser test (`e2e/phase2.cjs`)
  and watched for Content Security Policy violations.

## What holds

| Attack | Result |
|---|---|
| Guessing document, evaluation, form and file IDs as another supervisor, a teacher, a Form Author or a Cluster Head | 404, the same as a missing record; the attempt is audited. Nothing in the response names the school or file. |
| A second supervisor of the same school | Sees no report, no evaluation and no file, in lists, search, counts or by address. |
| Draft forms | Hidden from supervisors, Cluster Heads and teachers, including in the catalog. |
| Reusing a download link in another session, after signing out, after 5 minutes, or with a changed token | Refused (404, 401 or 410). |
| Keeping a link after sharing is revoked or the report is deleted | Refused: access is checked again when the file is fetched. |
| Claiming another person's upload, or a file already inside a report, for a new report | Refused (`file_not_usable`). |
| Files disguised by name (HTML or SVG named `.pdf`), PDFs with scripts, attachments or launch actions | Refused, or cleaned before they are stored (Phase 1 file service). |
| Header and path tricks in file names | The name is stored as text; downloads use a fixed ASCII name plus the encoded real name. |
| Dates used to reach outside an assignment | Report and visit dates must fall inside the supervisor's assignment window. |
| Cluster Head reading who opened a report | 403: access history is for the owner and admins only. |

## Findings and fixes

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | A report's stored file could also be opened through `/api/files/{id}/link`. That path records only a generic file event, so the view was missing from the supervisor's "Who opened it" (FR-L9) and did not mark the report as viewed (FR-D21). | Medium | Report files now open only through `/api/documents/{id}/link`; the file endpoint answers 404 for them. |
| 2 | Request bodies had no size limit. Upload routes check the size, but only after the server has spooled the whole body to disk, so one request could fill the disk. | Medium | The API refuses bodies over 60 MB for uploads and 2 MB otherwise, by declared length or by counting, before they are read (`app/body_limit.py`). Caddy enforces the same 60 MB. An admin cannot set the upload limit above it. |
| 3 | Table answers without a row limit, and form definitions without size limits. | Low | Tables default to at most 200 rows. Forms allow at most 50 sections, 300 questions per section, 200 options and 30 columns, and 2,000 characters per text. |
| 4 | Report search text had no length limit. | Low | At most 100 characters, as for the other searches. |
| 5 | Caddy replaced the API's own security headers, so file previews lost their stricter Content Security Policy. | Low | Caddy now only sets defaults; API responses keep theirs. Checked on the full stack (see below). |

## Accepted risks

- Download links carry a signed token in the URL path, so the web server's access log
  records it. A token works for 5 minutes, only in the session that made it, and only
  for someone who may still see the file.
- Form Authors are members of the implementation team and can write any form
  definition. Definitions are data, validated on every save, and never run as code.
- Watermarks deter casual sharing of a screenshot or a downloaded copy. They do not
  stop someone determined to remove them.
