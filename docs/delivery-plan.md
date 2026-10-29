# School Cluster Evaluation System: Delivery Plan

Companion to [requirements.md](requirements.md) v0.4. Requirement IDs refer
to that document. Open questions (Q1 to Q13) are in its section 21.

## Principles

- **Every phase ships.** Each phase ends with a release that real users can
  use.
- **Security and audit come first, not last.** Authentication, the
  hash-chained audit log, the file service, and the scoping layer are built
  in Phase 1. Every later feature plugs into them, so access rules are
  never added after the fact.
- **Isolation is tested from day one.** The permission matrix test (section
  19) grows with every endpoint. A phase cannot exit while any row fails.
- **Bilingual from day one.** Every screen, email, and PDF ships in English
  and Arabic in the phase that introduces it.
- **Online before offline.** Each workflow is built and proven online, then
  made offline-capable in Phase 4 using the same service layer.
- **Nothing is hard-deleted.** Every table gets soft delete and restore
  from its first migration.
- **Decisions before build.** A phase does not start until the open
  questions it depends on are answered.

## Definition of done (every phase)

A feature is done only when all of these hold:

1. Server-side scope checks are in place, and the permission matrix covers
   every new endpoint and role.
2. Every state change writes the audit entries in FR-L2 and FR-D55.
3. All user-facing text exists in English and Arabic and passes the
   pseudo-locale and RTL checks.
4. Migrations run against production-shaped data.
5. Keyboard and screen-reader checks pass on the new screens.
6. Metrics and error tracking cover the new jobs and endpoints.
7. User help text and an admin runbook entry exist where needed.

## Phase overview

| Phase | Name | Release | Blocking questions |
|---|---|---|---|
| 1 | Foundation and district structure | Staging; admins build the district | Q1, Q2, Q4, Q7, Q10, Q11, Q12, Q13 |
| 2 | Forms, supervision, and scanned reports | Pilot 1: one cluster | Q5, Q6, Q8 |
| 3 | Teacher participation | Pilot 1 with teachers | Q3 |
| 4 | Mobile, offline, and realtime | Pilot 2: whole district | none |
| 5 | Scoring, reporting, administration, and go-live | Production go-live | Q9 |
| 6 | After v1 | Incremental | per item |

---

## Phase 1: Foundation and district structure

**Goal:** a secure, audited, bilingual platform on the district's servers,
with the real district structure loaded.

**Scope**

- Server readiness on the district's hardware: public domain name, TLS
  certificate, firewall, separate backup server (Q10, Q13).
- Repository, CI, Docker Compose stack: API, worker, MySQL, ClamAV,
  TLS reverse proxy, encrypted file volume. Backups for database, files, and keys.
- Schema and migrations for all core tables, including forms, ministry
  catalog, and documents, so later phases add behavior, not structural
  rework. Soft delete on every table.
- Authentication: FR-A1 to FR-A16. Email codes and Google Authenticator
  (TOTP), recovery codes, admin reset, break-glass CLI, two-admin rule
  (FR-AD5).
- Hash-chained audit log with daily verification (FR-L1 to FR-L8).
- Job table and worker. Mail provider interface with Gmail API, the
  priority queue, the reserved security budget, invitation spreading, and
  the daily digest (FR-N5, FR-N6, FR-N8, FR-N9).
- File service: FR-FS1 to FR-FS4, envelope encryption, session-bound signed
  URLs.
- Scoped repository layer used by every query (the basis for FR-D12 and
  FR-E10).
- English and Arabic: language switch on every screen including sign-in,
  RTL layout, D/MM/YYYY dates, district time zone, bilingual email
  templates (FR-I1 to FR-I9). PWA shell, online only.
- Clusters, schools, contact teachers, teachers with the full field list,
  supervisors: CRUD, search, idempotent imports and exports (FR-S1 to
  FR-S8, FR-T1 to FR-T4, FR-T6, FR-P1 to FR-P5).
- Reference lists and custom fields for teachers and schools (FR-T5,
  FR-T6).

**Exit criteria**

- Login works end to end with both email codes and Google Authenticator;
  lockout, replay, and recovery codes verified.
- Hash verification passes; a simulated tamper is detected and alerted.
- The district's structure (2 admins, 30 supervisors, about 180 teachers)
  is built from import. Duplicates are rejected, and re-running an import
  changes nothing.
- Invitations for all users go out over two days within the Gmail budget,
  and login codes are never delayed.
- Every screen works in English and Arabic, and switching keeps unsaved
  input.
- File service rejects forged types, strips EXIF, sanitizes PDFs, and
  quarantines the EICAR file. A signed URL fails from another session.
- Backup and restore of database, files, and keys demonstrated once.

**Release:** staging on the district's servers. Admins load and check
their data.

**Status (Oct 29, 2026): built; waiting on the district to deploy**

Built and verified:

- Authentication with emailed codes and Google Authenticator, recovery codes,
  lockout, rate limits, sessions, CSRF protection, invitations, password reset,
  admin reset, break-glass CLI, two-admin rule.
- Hash-chained audit log, nightly verification with admin alerts, and an
  insert-only audit table for the application's database user.
- Mail queue with priorities, the reserved budget for sign-in codes,
  invitation spreading, daily digests, and Gmail API, SMTP or console
  providers.
- Clusters, schools, contact teachers, teachers with the district's field
  list, supervisors, reference lists, custom fields, scoped access (404 out of
  scope), optimistic locking, CSV and Excel import with preview and idempotent
  commit, and export.
- File service: type detection from content, PDF sanitization (scripts,
  attachments, forms, external actions), EXIF and GPS removal, HEIC to JPEG,
  TIFF to PDF, per-file encryption, ClamAV scanning, quarantine with alerts,
  checksums, quotas and limits, and download links bound to the session.
- Web app in English and Arabic with right-to-left layout, D/MM/YYYY dates,
  and a language switch on every screen and dialog that keeps unsaved input.
- PWA shell: installable manifest and icons, and an online-only service worker
  with a bilingual offline page. It never caches API data.
- Docker Compose stack, CI, deployment guide, and backup and restore scripts.

How it was verified:

- 84 backend tests against MySQL 8 with the real migrations, including a
  role permission matrix and a test against a real ClamAV server.
- Frontend unit tests, type-check and build in CI; both Docker images build
  in CI.
- The full Compose stack (MySQL, migrations, API, worker, ClamAV, Caddy with
  HTTPS) booted locally. The browser smoke test passed against it with no
  Content Security Policy violations, and the worker scanned an upload with
  the real ClamAV service.
- Backup and restore: a backup of the database and file volume was taken,
  every volume deleted, and the backup restored. The audit chain verified,
  every file decrypted with a matching checksum, Arabic file names survived,
  sign-in worked, and the app user still could not delete audit rows.
- PWA check (`e2e/pwa.cjs`): manifest served, service worker active, only
  static files cached, offline page shown in both languages.

Waiting on the district:

- Send real mail through the district's Gmail account (Q12). The Gmail API
  provider is tested only against a mocked Google server.
- Install on the district's server with its domain name (Q13), and run the
  smoke test there.
- Answers to the open Phase 1 questions: Q1, Q2, Q4, Q7, Q10, Q11, Q13.

Schema note: tables for forms, the ministry catalog and documents are added
by Phase 2 migrations. Adding tables needs no rework of existing ones.

Defaults used until the district answers: Western digits in Arabic (Q7) and
Google Authenticator required for District Admins and Form Authors (Q11).

---

## Phase 2: Forms, supervision, and scanned reports

**Goal:** admins publish ministry report forms, and supervisors in one
pilot cluster do their visit work in the system, either through online
forms or by scanning paper reports and submitting them to the admins.

**Scope**

- Ministry report catalog (FR-MR1 to FR-MR4).
- Form builder for the Form Author role: every question type, sections
  with respondents, validation, conditions, English and Arabic text, score
  fields, preview by role, language, and screen width (FR-F1 to FR-F10).
- Review and publishing by District Admins with D/MM/YYYY start and end
  dates, scheduled activation, extension and early close (FR-PB1 to
  FR-PB7).
- Assignments: assign, unassign, reassign, optimistic locking, board,
  history (FR-AS1 to FR-AS9).
- Evaluations with supervisor sections only; teacher sections are hidden
  until Phase 3. Drafts, submission, amendments, cancellation, visit
  windows, generated PDF reports with ministry IDs (FR-E1, FR-E4, FR-E5,
  FR-E7 to FR-E12). Score fields stored (FR-SC1).
- Scanned report vault, online:
  - Upload of files and multi-image documents with server-side PDF
    assembly, tagged with ministry report and version (FR-D1, FR-D2,
    FR-D4 to FR-D8).
  - Isolation and access rules, with full admin access (FR-D10 to FR-D16).
  - Submission to the District Admins, view tracking, acknowledge, return,
    new versions, lock after acknowledgement, forwarding to Cluster Heads,
    watermarks (FR-D20 to FR-D27).
  - Soft delete and restore, archive, retention flags, deactivation and
    reassignment rules (FR-D30 to FR-D34).
  - "My reports", "Report inbox", "Forwarded to me", metadata search, and
    the supervisor dashboard with coverage and access history (FR-D40 to
    FR-D44, FR-L9).
  - Quotas and rate limits (FR-D52, FR-D53).
- In-app notification center and email digest for assignment changes,
  form publishing, submissions, and report submissions, returns, and
  acknowledgements (FR-N1, FR-N2, FR-N4, FR-N7).

**Exit criteria**

- The Form Author builds the first ministry report form; an admin returns
  it once with comments, then publishes it with dates; it activates and
  closes on the right days in district time.
- A Form Author gets 404 on all district data.
- Every scanned report and form acceptance criterion in section 18 passes,
  including the same-school second supervisor case and the
  post-reassignment case.
- Permission matrix green for every form, evaluation, and document
  endpoint.
- A supervisor completes a school evaluation and a teacher evaluation
  (supervisor sections) and downloads the PDF in both languages.
- A supervisor scans and submits a report; an admin returns it; the
  supervisor resubmits; the admin acknowledges and forwards it; the
  supervisor sees each step on their dashboard.
- Focused security review of document and form endpoints (ID guessing, URL
  reuse, upload attacks) with no open high findings.

**Release:** Pilot 1, one cluster. Paper is still allowed as a fallback.

**Status (Oct 29, 2026): built; security review and district pilot to come**

Built:

- Ministry report catalog with report and version IDs; Form Author builder
  for every question type, sections by respondent, conditions on earlier
  questions, English and Arabic text, score weights; preview by respondent,
  language and screen width.
- Review by District Admins: return with comments, publish with D/MM/YYYY
  start and end dates in district time, change the end date, close early,
  confirm overlapping windows.
- Assignment board with workload, assign, end, reassign with a choice for
  open evaluation drafts, history, and optimistic locking.
- Evaluations (supervisor sections): drafts, server-checked answers shown
  next to each question, submission with optional location, amendments with
  reasons, cancellation, and PDF reports in English and Arabic with the
  ministry IDs.
- Scanned report vault: photos and PDFs from the device or camera joined into
  one PDF in order; "My reports", the admin inbox and "Forwarded to me";
  submit, withdraw, return, new versions and corrections, acknowledge,
  forward to the Cluster Head and revoke, soft delete and restore, archive;
  watermarked copies for everyone but the owner; access history; the
  supervisor dashboard with coverage and monthly counts.
- Notification center with per-type, per-channel choices and text in both
  languages; email copies in the daily digest; a daily reminder to admins of
  reports waiting past the acknowledgement period.

How it was verified:

- 141 backend tests against MySQL 8 with the real migrations, including the
  permission matrix for every Phase 2 endpoint, the same-school second
  supervisor case and the post-reassignment case.
- Browser test (`e2e/phase2.cjs`, seeded by `e2e/seed_phase2.py`) through
  the screens of every role: the author builds a form, an admin returns and
  then publishes it, the Cluster Head assigns two supervisors to one school,
  a supervisor evaluates, downloads the Arabic PDF and amends, uploads a
  photo and a PDF as one report, the second supervisor gets nothing even by
  address, the admin opens, returns and acknowledges the report and shares it
  with the Cluster Head, who can then read it. Also checks notifications and
  the dashboard in Arabic, and the upload dialog on a phone screen. No page
  errors and no Content Security Policy violations.
- Running it found and fixed: a new ministry report hidden from its author
  until it had a version; question editors folding while being typed in;
  a stale version sent when "Send for review" followed "Save"; and a server
  error on browser device times with a time zone.

Not yet done:

- Teacher evaluations were tested through the API, not yet in the browser.
- The focused security review of document and form endpoints.
- Phase 2 on the full Compose stack with the real ClamAV service. Phase 1
  was verified there; CI builds the images.
- The pilot cluster's data and the first real ministry report form.

---

## Phase 3: Teacher participation

**Goal:** teachers in the pilot cluster answer their sections and
requests.

**Scope**

- Teacher sections on School and Teacher evaluations; contact-teacher
  routing and waiver (FR-E2, FR-E3, FR-E6, FR-S6).
- Standalone requests, returns, reminders, overdue handling (FR-R1 to
  FR-R6).
- Teacher transfer rules (section 6.1).
- Additional teacher fields configured from Q3 (FR-T5).
- Teacher onboarding at scale within the mail budget.

**Exit criteria**

- A teacher completes a request; the requester returns it and the teacher
  resubmits; all steps audited.
- Reminders go out in the daily digest, and login codes are never delayed.
- A teacher gets 404 for another teacher's request and for every scanned
  report.

**Release:** Pilot 1 extended to all teachers in the pilot cluster.

---

## Phase 4: Mobile, offline, and realtime

**Goal:** the system works in the field on phones, with poor or no
connectivity, and screens update live.

**Scope**

- Realtime broadcaster with scope filtering, WebSocket and SSE fallback,
  reconnect and refetch (FR-RT1 to FR-RT4).
- Web Push (FR-N3).
- Offline: caching, IndexedDB drafts, ordered queue, idempotent replay,
  conflict choice, storage warnings, clock skew flags, sign-out wipe, forms
  closed while offline (FR-PW1 to FR-PW13).
- Camera scanning: multi-page capture, edge detection, crop, deskew,
  contrast, reorder, on-device PDF assembly and compression (FR-D3).
- Resumable, offline-queued report uploads (FR-D6).

**Exit criteria**

- An offline draft and an offline 10-page scan survive an app restart and
  sync once online on Android and iPhone, with no duplicates.
- Status changes appear on open screens within 2 seconds.
- A second supervisor's open screen receives no event about another
  supervisor's reports.
- Sign-out on a shared phone leaves no cached data.

**Release:** Pilot 2, the whole district.

---

## Phase 5: Scoring, reporting, administration, and go-live

**Goal:** the district can score, manage, report on, and rely on the
system in production.

**Scope**

- Scoring rule sets from the district's formula, server-side calculation,
  recorded recalculation, scores on evaluations, PDFs, dashboards, and
  exports (FR-SC2, FR-SC3).
- Role dashboards and standard reports, PDF and Excel exports, report ZIP
  export (FR-RP1 to FR-RP5).
- Audit viewer and audited exports (FR-L5).
- Admin settings, locked-account view, support view, per-person data
  export (FR-AD1 to FR-AD4).
- Hardening: OWASP scan, external penetration test, load test at design
  scale, restore test with file checksums, accessibility pass,
  localization pass, device checks.
- Operations: runbooks for backup, restore, break-glass, authenticator
  resets, quarantine, mail budget alerts, moving to a paid mail plan, and
  incident response. Training material per role in English and Arabic.

**Exit criteria**

- Scores match the district's formula on a set of worked examples it
  supplies.
- Every acceptance criterion in section 18 passes on the release build.
- Penetration test has no open critical or high findings.
- Load test meets section 15 targets.
- Restore test recovers data within the RTO.
- Reports export correctly in English and Arabic.
- District sign-off.

**Release:** production go-live.

---

## Phase 6: After v1

Ordered by district priority once v1 is live. Each item needs its own
short requirements update before work starts.

- OCR of scanned reports and full-text search, with the FR-D12 rule on the
  index.
- Automatic routing of reports to Cluster Heads, if Q5 asks for it.
- Form building by District Admins, if Q6 asks for it.
- Move from the free Gmail account to Google Workspace or an SMTP relay
  when the mail budget alerts often (configuration only, FR-N9).
- Multi-instance deployment with an external broadcaster for higher
  availability.
- Cross-district reporting.
- Native store apps, if PWA limits on iOS become a blocker.

## Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Ministry report formats arrive late (Q8) | Phase 2 slips | Start with one report; the scanned report vault lets Pilot 1 run on paper while forms are built |
| Ministry issues new versions often | Rework for every version | Copy-forward builder (FR-MR4) and schema tests make each new version a small change |
| Free Gmail account throttled or suspended for automated sending | Login codes and invitations fail | Reserved security budget, digests, authenticator app for admins, dedicated account (Q12), provider switch by configuration |
| Servers not reachable from the internet (Q13) | Phones cannot sign in or receive push | Resolve in Phase 1 before any pilot |
| Single on-site server and backups in one building | Data loss in a site incident | Separate backup server now; off-site encrypted copy recommended (Q10) |
| iOS evicts offline storage | Lost offline work | Persistent storage request, at-risk warnings, small queue limits (FR-PW8, FR-PW9) |
| Poor scan quality on low-end phones | Unreadable reports, many returns | On-device cleanup, preview before upload, return-with-comment flow |
| A scoping bug exposes another supervisor's reports | Privacy breach and loss of trust | Single scoped repository, permission matrix in CI, 404 on out-of-scope IDs, external penetration test |
| Scoring formula arrives late (Q9) | Phase 5 slips | Scores are stored from Phase 2; scoring can ship after go-live without data migration |
