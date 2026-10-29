# School Cluster Evaluation System: Delivery Plan

Companion to [requirements.md](requirements.md) v0.3. Requirement IDs refer
to that document. Open questions (Q1 to Q18) are in its section 21.

## Principles

- **Every phase ships.** Each phase ends with a release that real users can
  use. No phase is "infrastructure only" except Phase 1, and even that one
  gives admins a working district.
- **Security and audit come first, not last.** Authentication, the
  hash-chained audit log, the file service, and the scoping layer are built
  in Phase 1. Every later feature plugs into them, so access rules are
  never added after the fact.
- **Isolation is tested from day one.** The permission matrix test (section
  19) grows with every endpoint. A phase cannot exit while any row fails.
- **Online before offline.** Each workflow is built and proven online, then
  made offline-capable in Phase 4 using the same service layer.
- **Decisions before build.** A phase does not start until the open
  questions it depends on are answered.

## Definition of done (every phase)

A feature is done only when all of these hold:

1. Server-side scope checks are in place, and the permission matrix covers
   every new endpoint and role.
2. Every state change writes the audit entries in FR-L2 and FR-D55.
3. All user-facing text is translatable and passes the pseudo-locale and
   RTL checks.
4. Migrations run against production-shaped data.
5. Keyboard and screen-reader checks pass on the new screens.
6. Metrics and error tracking cover the new jobs and endpoints.
7. User help text and an admin runbook entry exist where needed.

## Phase overview

| Phase | Name | v0.2 milestones | Release | Blocking questions |
|---|---|---|---|---|
| 1 | Foundation and district structure | M0, M1 | Staging; pilot admins build the district | Q1, Q4, Q5, Q6, Q7, Q9, Q18 |
| 2 | Supervision core and scanned reports | M2, M3 (supervisor part) | Pilot 1: one cluster | Q2, Q11, Q12, Q13, Q14, Q15, Q16 |
| 3 | Teacher participation | M3 (teacher part), M4 | Pilot 1 with teachers | Q10, Q17 |
| 4 | Mobile, offline, and realtime | M5, M6 | Pilot 2: whole pilot district | none |
| 5 | Reporting, administration, and go-live | M7, M8 | Production go-live | Q3, Q8 |
| 6 | After v1 | new | Incremental | per item |

---

## Phase 1: Foundation and district structure

**Goal:** a secure, audited platform with the district's real structure
loaded.

**Scope**

- Repository, CI, Docker Compose stack: API, worker, MySQL, object storage,
  ClamAV, TLS reverse proxy. Backups for database and files.
- Schema and migrations for all core tables, including the document tables,
  so later phases add behavior, not structural rework.
- Authentication: FR-A1 to FR-A11, sessions, break-glass CLI, two-admin
  rule (FR-AD5).
- Hash-chained audit log with daily verification (FR-L1 to FR-L4, FR-L6 to
  FR-L8).
- Job table and worker. Gmail sending with the priority queue and quota
  counter for security mail and invitations (FR-N5, FR-N6).
- File service: FR-FS1 to FR-FS4, envelope encryption, session-bound signed
  URLs.
- Scoped repository layer used by every query (the basis for FR-D12 and
  FR-E10).
- i18n scaffolding, RTL layout, district time zone, PWA shell (online
  only).
- Clusters, schools, contact teachers, teachers, supervisors: CRUD, search,
  idempotent imports and exports (FR-S1 to FR-S8, FR-T1 to FR-T4, FR-P1 to
  FR-P5).

**Exit criteria**

- Login with email 2FA works end to end; lockout and rate limits verified.
- Hash verification passes; a simulated tamper is detected and alerted.
- The pilot district's structure is built from import; duplicates are
  rejected and re-running an import changes nothing.
- File service rejects forged types, strips EXIF, sanitizes PDFs, and
  quarantines the EICAR file. A signed URL fails from another session.
- Backup and restore of database and files demonstrated once.

**Release:** staging. Pilot admins and Cluster Heads load and check their
data.

---

## Phase 2: Supervision core and scanned reports

**Goal:** supervisors in one pilot cluster do their visit work in the
system, either through online forms or by scanning paper reports, and share
reports with their Cluster Head.

**Scope**

- Assignments: assign, unassign, reassign, optimistic locking, board,
  history (FR-AS1 to FR-AS9).
- Form versioning and the section engine (FR-F1 to FR-F8). Evaluations with
  supervisor sections only; teacher sections are hidden until Phase 3.
  Drafts, submission, amendments, cancellation, visit windows (FR-E1,
  FR-E4, FR-E5, FR-E7 to FR-E11).
- Scanned report vault, online:
  - Upload of files and multi-image documents with server-side PDF assembly
    (FR-D1, FR-D2, FR-D4 to FR-D8).
  - Isolation and access rules (FR-D10 to FR-D16).
  - Sharing with the Cluster Head, view tracking, acknowledge, return, new
    versions, lock after acknowledgement, watermarks (FR-D20 to FR-D27).
  - Soft delete and restore, deactivation and reassignment rules (FR-D30,
    FR-D31, FR-D33, FR-D34).
  - "My documents" and "Shared with me" lists and metadata search (FR-D40
    to FR-D42).
  - Quotas, rate limits, access history for owners (FR-D52, FR-D53,
    FR-L9).
- In-app notification center and email for assignment changes, submissions,
  and document shares, returns, and acknowledgements (FR-N1, FR-N2, FR-N4,
  FR-N7).

**Exit criteria**

- Every document acceptance criterion in section 18 passes, including the
  same-school second supervisor case and the post-reassignment case.
- Permission matrix green for every document and evaluation endpoint.
- Two concurrent reassignments: one succeeds, one gets 409.
- A supervisor completes a school evaluation and a teacher evaluation
  (supervisor sections), and scans, shares, has returned, and resubmits a
  report.
- Focused security review of document endpoints (ID guessing, URL reuse,
  upload attacks) with no open high findings.

**Release:** Pilot 1, one cluster. Supervisors and the Cluster Head use it
for real visits. Paper is still allowed as a fallback.

---

## Phase 3: Teacher participation

**Goal:** teachers in the pilot cluster answer their sections and requests.

**Scope**

- Teacher sections on School and Teacher evaluations; contact-teacher
  routing and waiver (FR-E2, FR-E3, FR-E6, FR-S6).
- Standalone requests, returns, reminders, overdue handling (FR-R1 to
  FR-R6).
- Teacher transfer rules (section 6.1).
- Full mail priority queue with reminder and informational traffic, quota
  alerts (FR-N6).
- Teacher onboarding: invitations at scale, verified email checks (FR-A10,
  FR-T4).

**Exit criteria**

- A teacher completes a request; the requester returns it and the teacher
  resubmits; all steps audited.
- OTP mail is never delayed by reminder mail at full queue.
- A teacher gets 404 for another teacher's request and for any document.

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
  conflict choice, storage warnings, clock skew flags, sign-out wipe
  (FR-PW1 to FR-PW12).
- Camera scanning: multi-page capture, edge detection, crop, deskew,
  contrast, reorder, on-device PDF assembly and compression (FR-D3).
- Resumable, offline-queued document uploads (FR-D6).

**Exit criteria**

- An offline draft and an offline 10-page scan survive an app restart and
  sync once online on Android and iPhone, with no duplicates.
- Status changes appear on open screens within 2 seconds.
- A second supervisor's open screen receives no event about another
  supervisor's documents.
- Sign-out on a shared phone leaves no cached data.

**Release:** Pilot 2, every cluster in the pilot district.

---

## Phase 5: Reporting, administration, and go-live

**Goal:** the district can manage, report on, and rely on the system in
production.

**Scope**

- Role dashboards and standard reports, PDF and Excel exports, document ZIP
  export (FR-RP1 to FR-RP5).
- Audit viewer and audited exports (FR-L5).
- Admin settings, locked-account view, support view with content hiding,
  two-admin content access for documents (FR-AD1 to FR-AD4, FR-D15).
- Retention and purge jobs, erasure procedure (FR-D32, FR-D35, section
  13.1).
- Score fields exported; aggregation only if Q3 is answered.
- Hardening: OWASP scan, external penetration test, load test at target
  scale, restore test with file checksums, accessibility pass, localization
  pass, device checks.
- Operations: runbooks for backup, restore, break-glass, quarantine, quota
  alerts, and incident response. Training material per role.

**Exit criteria**

- Every acceptance criterion in section 18 passes on the release build.
- Penetration test has no open critical or high findings.
- Load test meets section 15 targets.
- Restore test recovers data within the RTO.
- Reports export correctly in each enabled locale.
- District sign-off.

**Release:** production go-live in the pilot district. Further districts
are onboarded as separate deployments.

---

## Phase 6: After v1

Ordered by district priority once v1 is live. Each item needs its own
short requirements update before work starts.

- OCR of scanned reports and full-text search, with the FR-D12 filter on
  the index.
- Supervisor-to-supervisor sharing, if Q12 approves it (FR-D26).
- Score aggregation, once scoring rules are defined.
- Trusted devices to reduce OTP prompts, if Q7 allows.
- Multi-instance deployment with an external broadcaster for higher
  availability.
- Teacher access to reports about them, if Q17 allows.
- Form builder for district-authored forms.
- Cross-district reporting.
- Native store apps, if PWA limits on iOS become a blocker.

## Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Form content arrives late (Q2) | Phase 2 slips | Scanned reports let Pilot 1 start with paper forms; online forms follow |
| iOS evicts offline storage | Lost offline work | Persistent storage request, at-risk warnings, small queue limits (FR-PW8, FR-PW9) |
| Gmail quota too low | OTP or invitations delayed | Priority queue and 80% alert; confirm plan in Q6 before Phase 1 |
| Poor scan quality on low-end phones | Unreadable reports, many returns | On-device cleanup, preview before upload, return-with-comment flow |
| A scoping bug exposes another supervisor's documents | Privacy breach and loss of trust | Single scoped repository, permission matrix in CI, 404 on out-of-scope IDs, external penetration test |
| Storage growth beyond estimate | Cost and backup time | Quotas, compression, 80% alerts, retention purge |
