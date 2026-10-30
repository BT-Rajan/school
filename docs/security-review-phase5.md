# Phase 5 security review: scoring, reports, exports, admin tools, release scan

Date: 30 October 2026. Scope: the endpoints added in Phase 5 (scoring rule sets and
recalculation, standard reports and their exports, global search, dashboards, the report ZIP
export, the audit viewer and its export, admin settings and the district logo, failed sign-ins,
the support view and the per-person export), and the release scan of the whole application on
the full Compose stack. The Phase 5 exit criterion for security is "no open critical or high
findings" from an external penetration test. That test is the district's to commission; this
review and the scans below found no critical, high or medium findings open.

## Method

- Read the access rules and every new code path that returns records: `app/reporting/*`,
  `app/admin/*`, `app/scoring/service.py`, `app/api/system.py`, `app/auth/deps.py`.
- Wrote attacks as tests that run in CI: `backend/tests/test_reporting.py`, `test_admin.py`,
  `test_scoring.py`, `test_retention.py`.
- OWASP ZAP 2.16 (stable image) against the Compose stack (Caddy with HTTPS, MySQL, ClamAV):
  a passive baseline of the web app, and an active API scan of the 126 endpoints in the app's
  own OpenAPI description, signed in as a District Admin (session cookie and CSRF header added
  to every request). Sign-in, sign-out and session endpoints were left out of the active scan so
  it would not end its own session; they are covered by `test_auth.py` (brute force, replay,
  lockout, rate limits).
- Dependency audits: `pip-audit` on the API's Python environment, `npm audit --omit=dev` on the
  web app; `bandit` over `backend/app`.

## What holds

| Attack | Result |
|---|---|
| Reports, exports, search and dashboard counts as a second supervisor of the same school, another cluster's Cluster Head, a teacher or a Form Author | Nothing of others' work: each starts from the same scope rule as the screens (evaluations, requests and documents each have one `visible_query`). Teachers and Form Authors get 403. |
| Search used to probe other roles' lists | A role only searches the lists it has; no permission denial is recorded for lists it cannot open. |
| Exports without a trace | Every Excel, PDF and CSV export, the ZIP and the audit export are audited with who, the filters and the row count or document IDs. |
| Another admin downloading an admin's ZIP | 404: only the admin who asked can link it. ZIPs are stored encrypted, virus checked, and every page is watermarked with the requesting admin's name. |
| More than 200 reports in one ZIP | Refused (`export_too_many`). |
| Support view used to change something | Writes are refused on the server (403, audited as a denial) and never sent by the web app while a view is open. A view needs a reason, lasts at most 30 minutes, only for non-admin accounts, only for the admin who started it; every page viewed is audited against the admin, and the user is told at their next sign-in. |
| Support view leaving data on the admin's device | Nothing seen in a view is kept in the offline store, and the shared-phone owner check is not triggered. |
| Per-person export leaking secrets | Password and code hashes, authenticator secrets, tokens and file keys are left out (tested). |
| Settings used for header injection or lock-out | The sender name refuses line breaks and angle brackets; English cannot be turned off; the admin role always needs an authenticator; every value is range checked. |
| Logo upload carrying script | Only PNG or JPEG after the file service's type sniffing; served with `nosniff`. |
| Live updates reaching the wrong people after the load-test speed-up | A report's audience is now worked out for everyone connected at once (`documents.access.audience`). A test compares it with `can_access` for every user and every report state (draft, submitted, forwarded, forward revoked, deleted, withdrawn); at design scale 400 other supervisors' connections received nothing. |
| Permanent deletion | No endpoint deletes a record (`test_retention.py`); the only DELETE marks a sign-in session revoked. |
| Rule set changing stored scores silently | Active rule sets are fixed; scores change only through a recorded recalculation, each change audited. |
| Login brute force during the scan | The unauthenticated scan used up the 50 sign-ins per hour per address and was answered 429, as designed. |

## Findings and fixes

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | During development of the support view, the web app sent writes from the viewed user's screens without the view's header, so they went out as the admin. The server refused them where the admin had no right, but an admin could have acted under their own name from someone else's screen. | Medium | The web app refuses every write while a view is open (except ending it and signing out); the server refuses writes carrying the header. Found in the browser check before release. |
| 2 | ZAP: "Private IP disclosure" on the failed sign-ins list. | Informational | The list shows admins the address of failed sign-ins on purpose (FR-AD2). The address seen was Docker's gateway only because the scanner ran on the host. |
| 3 | ZAP: "Unexpected Content-Type" on unknown paths (the app's HTML) and on the Server-Sent Events stream. | Informational | As designed. |
| 4 | Bandit: SHA-1 in the breached-password check. | False positive | The range API needs SHA-1; only five characters of it leave the server. Marked `usedforsecurity=False`. |
| 5 | Java clients without SNI could not connect to a dotless host name. | Low | Caddy now has `default_sni` set to the site's domain, so clients that send no server name get its certificate. |

Scan totals: baseline 0 failures, 2 informational; API scan (signed in) 0 failures, 113 rules
passed, 2 low warnings (rows 2 and 3). Dependency audits: no known vulnerabilities.

## For the external penetration test

The test should cover what section 19 names, on the release build:

- Access to other users' objects by ID: documents, files, evaluations, requests, rule sets,
  exports (ZIP files), support sessions.
- Signed URL abuse: reuse in another session, after sign-out, after 5 minutes, tampering.
- Upload attacks: type confusion, active PDFs, oversized and slow bodies, resumable upload
  offsets.
- Second-factor bypass: replay, recovery codes, lockout, break-glass.
- The support view: read-only enforcement and audit.

Test accounts for each role can be created with the seed used by the browser tests
(`e2e/seed_phase4.py`) on a staging copy, never on production.
