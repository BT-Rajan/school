# School Cluster Evaluation System: Requirements v0.3

Oct 29, 2026 · Supersedes v0.2 ([archived](archive/School_Cluster_Evaluation_System_Requirements_v0.2.docx))

This revision adds a **scanned report vault**: supervisors upload scanned
reports and share them with their Cluster Head, and no supervisor can ever
see another supervisor's documents. It also closes the gaps that a second
stress test found in v0.2 and replaces the milestone list with a phased
delivery plan ([delivery-plan.md](delivery-plan.md)).

Requirement IDs from v0.2 are unchanged. New requirements are marked
**(new)** and changed ones **(changed)**. Items marked **[Confirm]** need a
district decision; they are collected in section 21.

---

## Part A: What changed in v0.3

### A.1 New capability: scanned report vault

Supervisors often fill paper forms during visits, or collect signed paper
reports from schools. They need to scan those reports, upload them, and
share them with their Cluster Head. Section 9 specifies this. Its core rule:

> A document is visible only to the supervisor who uploaded it and to the
> recipients that supervisor explicitly shares it with. No other supervisor
> can see, list, search, or count it. That includes a supervisor assigned
> to the same school and one who takes the school over later.

**Interpretation to confirm:** the request said supervisors share reports
"with supervisor". v0.3 reads this as the Cluster Head, the supervisor's
reporting line. Sharing between supervisors would conflict with the
isolation rule, so it is off in v1 and listed as open question Q12.

### A.2 Gaps found in v0.2

| # | Gap in v0.2 | Resolution in v0.3 |
|---|---|---|
| G1 | Attachments had no per-object access rule. Any signed URL worked for whoever held it. | One file service for all stored files. Every download passes a server-side access check. Signed URLs last 5 minutes and are bound to the requesting session (FR-D13, FR-FS4). |
| G2 | Backups and RPO/RTO covered only the database. | File storage is backed up on the same schedule. Restore tests verify a sample of file checksums (FR-D54, section 15). |
| G3 | No district time zone. "Due date" and "overdue" were ambiguous. | District time zone setting. Due dates end at 23:59 district time (FR-AD1, FR-R2). |
| G4 | Supervisor visibility of other supervisors' evaluations was implied, not stated. | Explicit rule: a supervisor sees only their own evaluations and attachments (FR-E10). |
| G5 | A supervisor moving to another cluster was undefined. | Cluster transfer rules (section 6.2). |
| G6 | Nothing stopped deactivating the second-to-last admin. | Deactivating or demoting an admin is blocked while it would leave fewer than two active admins (FR-AD5). |
| G7 | The admin support view (FR-AD3) could expose private content. | The support view hides document content, answers to free-text fields, and attachments (changed FR-AD3). |
| G8 | No general API rate limit or upload limits. | Per-user and per-IP API limits. Upload size, page and quota limits (section 15, FR-D52, FR-D53). |
| G9 | Uploads trusted the file extension. A PDF with active content or an image with GPS EXIF was stored as is. | Content-type sniffing, PDF sanitization, EXIF stripping, quarantine on failed scan (FR-FS2, FR-FS3). |
| G10 | Offline visit dates came from the device clock. | The server checks client timestamps against receipt time and flags skew over 24 hours (FR-PW11). |
| G11 | Cached data stayed in the browser after sign-out on shared devices. | Sign-out clears IndexedDB, Cache Storage and pending queue after warning about unsent items (FR-PW12). |
| G12 | Existence leaks: 403 on someone else's object confirms it exists. | Objects outside scope return 404. The denial is still audited (FR-D11, section 17). |

---

## Part B: Requirements

### 1. Purpose

Give a district one system to organize schools into clusters, assign
supervisors to visit them, collect evaluations through fixed forms, and hold
scanned visit reports. Every change is tracked in a tamper-evident log,
status updates reach users in real time, phones work offline, and each
supervisor's documents stay private to them and the people they share with.

### 2. Scope and deployment

- One deployment per district, with its own database, file storage,
  secrets, and mail account.
- A deployment holds multiple clusters. A supervisor belongs to one cluster
  at a time.
- PWA only. No native store apps in v1.
- Out of scope in v1: form builder, machine translation of user text,
  scoring rules until the district defines them, OCR of scanned reports,
  payments, timetables, student records, attendance, and cross-district
  reporting.

### 3. Users and roles

| Role | Created by | Scope | Core capabilities |
|---|---|---|---|
| District Admin | Installer; at least two required | District | Clusters and Cluster Heads, system settings, locales, mail settings, audit viewer, account recovery. No routine access to document content (FR-D15). |
| Cluster Head | District Admin | Own cluster | Schools, teachers, supervisors; assign, unassign, reassign; send requests; progress and reports; receive, acknowledge and return documents shared with them |
| Supervisor | Cluster Head | Assigned schools; own work | Complete evaluations; view assigned schools and their teachers; own history; upload, manage and share own scanned reports |
| Teacher | Cluster Head or import | Own school and own requests | Complete requests; act as contact teacher where designated; own submissions |

**Role rules**

- A school belongs to exactly one cluster. A teacher belongs to exactly one
  school.
- Each school has at most one designated contact teacher at a time.
- A school can have several supervisors over time, and zero or more active
  ones at any moment.
- **(new)** Supervisors are isolated from each other. Being assigned to the
  same school grants no access to another supervisor's evaluations,
  attachments or documents.
- Users are deactivated, never hard-deleted. Erasure is handled by
  anonymization (section 13).

### 4. Authentication and account security

- **FR-A1** Email and password login.
- **FR-A2** Email 2FA on every login: a 6-digit code, valid 10 minutes,
  single use, stored hashed.
- **FR-A3** Lock after 5 failed codes for 15 minutes, or until an admin
  unlocks.
- **FR-A4** Limit code requests to 3 per account per 10 minutes and 30 per
  IP per hour.
- **FR-A5** Password reset uses the same email code mechanism.
- **FR-A6** Idle timeout of 12 hours. Forced sign-out on role change or
  deactivation.
- **FR-A7** Passwords hashed with Argon2id. Codes hashed with HMAC.
- **FR-A8** Users can view active sessions and revoke any of them.
- **FR-A9** Break-glass 2FA reset: a server-side CLI command that requires
  confirmation, writes a critical audit entry, and emails all other admins.
- **FR-A10** Teachers and supervisors need a verified personal or school
  email before activation.
- **FR-A11 (new)** Password policy: at least 10 characters, checked against
  a list of known breached passwords. No forced periodic rotation.

### 5. Clusters, schools, and contact teachers

- **FR-S1** Admin creates, edits, and deactivates clusters. Each has a
  name, a code, and one Cluster Head.
- **FR-S2** Cluster Head creates, edits, and deactivates schools. Required:
  name, school code (unique in the district), address, type, medium of
  instruction, contact details. Admin can configure extra fields.
- **FR-S3** Search and filter by name, code, status, supervisor, and
  contact teacher, with pagination.
- **FR-S4** Import schools from CSV or Excel, with a preview and per-row
  errors before commit. Idempotent on school code.
- **FR-S5** Export school lists to CSV or Excel.
- **FR-S6** Cluster Head designates or changes a school's contact teacher.
  The previous contact teacher's open school-level requests move to the new
  one, with notification.
- **FR-S7** A school cannot be deactivated while it has active assignments.
  Open evaluations are frozen, not deleted. Documents linked to it are kept.
- **FR-S8** Schools with no active supervisor are flagged on the Cluster
  Head dashboard.

### 6. Teachers and supervisors

- **FR-T1** Cluster Head creates, edits, searches, and deactivates
  teachers. Required: staff ID (unique in the district), name, school,
  verified email.
- **FR-T2** Import teachers from CSV or Excel, idempotent on staff ID. Each
  new valid row sends an invitation.
- **FR-T3** Transfer a teacher to another school in the same cluster. The
  transfer is recorded with dates, under the rules in 6.1.
- **FR-T4** The invitation link sets the password and enrolls email 2FA. It
  expires in 72 hours and is single use.
- **FR-P1** Cluster Head creates, edits, searches, and deactivates
  supervisors. Required: staff ID (unique in the district), name, verified
  email.
- **FR-P2** Import supervisors from CSV or Excel, idempotent on staff ID.
- **FR-P3 (changed)** Supervisor deactivation is blocked while active
  assignments exist. Before deactivation, the supervisor is asked to share
  or delete unshared documents. The Cluster Head sees only how many
  unshared documents remain, never their titles or content.
- **FR-P4** The supervisor profile shows current assignments, workload,
  evaluation counts, and shared document counts.

#### 6.1 Teacher transfer rules

- Open evaluations about the teacher stay with their supervisor.
- Open requests to the teacher stay with the teacher. The original
  requester keeps visibility.
- If the new school has a contact-teacher link to an open evaluation, the
  supervisor is notified and must confirm the link.

#### 6.2 Supervisor cluster transfer (new)

- **FR-P5** Admin moves a supervisor to another cluster. All assignments in
  the old cluster must end first (same rule as FR-P3).
- The supervisor keeps access to their own past evaluations and documents,
  read-only for records from the old cluster.
- Documents already shared stay with the old cluster's Cluster Head. The
  new Cluster Head gets no access to them.

### 7. Assignments

- **FR-AS1** Assign: link a supervisor to a school with a start date and
  optional end date. An overlapping duplicate of the same pair is rejected.
- **FR-AS2** Unassign: end an active assignment. Blocked while the
  supervisor has draft evaluations on the school, unless each draft is
  transferred to another active supervisor or cancelled with a reason.
  Submitted evaluations stay with their supervisor.
- **FR-AS3** Reassign: a school moves from supervisor A to supervisor B in
  one transaction, recorded as an end and a start so history is kept. Open
  drafts need an explicit choice: transfer or cancel.
- **FR-AS4** Assignment board: schools against supervisors, with filters.
  Drag and drop on desktop; a list with actions on mobile.
- **FR-AS5** Assignment history per school and per supervisor, showing who
  acted, when, and the reason.
- **FR-AS6** An evaluation's visit date must fall inside an active
  assignment window. Enforced on save and on submit.
- **FR-AS7** Every assignment write uses optimistic locking. A stale write
  returns a conflict, and the user sees the current state before retrying.
- **FR-AS8** Cluster Head vacancy: admin reassigns the cluster to another
  Cluster Head. Supervisors and assignments are unaffected. Documents shared
  with the cluster's Cluster Head become visible to the new one (FR-D20).
- **FR-AS9 (new)** Draft transfer under FR-AS2/FR-AS3 moves the evaluation
  draft only. Documents never move between supervisors.

### 8. Forms and evaluations

#### 8.1 Form definitions

- **FR-F1** Forms are fixed by the system and shipped as versioned
  definitions. Cluster Heads cannot create or edit forms.
- **FR-F2** A form is a schema of sections, questions, validation rules,
  conditional logic, and translations, stored as a versioned JSON document.
- **FR-F3** Each section has a respondent: supervisor or teacher. Teacher
  sections are delivered as requests.
- **FR-F4** Published form versions are immutable. An evaluation keeps the
  version it started with.
- **FR-F5** Question types: short text, long text, number with range,
  single choice, multiple choice, date, yes/no, rating scale, and file
  attachment (photo or PDF, through the file service in 10.1).
- **FR-F6** Conditional visibility based on earlier answers.
- **FR-F7** Every question, option, and label is translatable, with
  fallback to the district default locale.
- **FR-F8** Score fields may exist. v1 stores and exports them; aggregation
  rules come later.

#### 8.2 Evaluations

- **FR-E1** Two subjects: School and Teacher.
- **FR-E2** A School evaluation has supervisor sections and teacher
  sections. Teacher sections go to the school's contact teacher.
- **FR-E3** A Teacher evaluation has supervisor sections and teacher
  sections. Teacher sections go to the teacher being evaluated.
- **FR-E4** The supervisor starts an evaluation from an assigned school or
  teacher, picks the form, and saves drafts at any time, online or offline.
- **FR-E5** Statuses: Draft, Submitted, Amended, Cancelled. Each section is
  Not started, In progress, Submitted, or Returned.
- **FR-E6** Submission requires all required sections submitted by their
  respondents. A school evaluation cannot be submitted until the contact
  teacher's section is submitted, or the Cluster Head waives it with a
  reason.
- **FR-E7** Submitted content is locked. Corrections are amendments that
  store the reason and the prior answers, and write an audit entry.
- **FR-E8** Visit record: visit date (required), optional location captured
  at submission with permission, and visit notes.
- **FR-E9** Cancelling requires a reason and is recorded.
- **FR-E10 (new)** A supervisor sees only evaluations they own, including
  attachments. The Cluster Head sees all evaluations in the cluster. A
  teacher sees only the sections addressed to them.
- **FR-E11 (new)** A supervisor can link their own scanned documents to an
  evaluation as supporting evidence. The link does not change who can see
  the document. A Cluster Head viewing the evaluation sees only linked
  documents that have also been shared with them.

#### 8.3 Teacher requests

- **FR-R1** A request is a teacher-respondent section of an evaluation, or
  a standalone request type approved for the district, such as a school
  profile update. Standalone requests use system-defined forms only.
- **FR-R2 (changed)** Requests have a due date, instructions, and a
  reminder schedule. A due date ends at 23:59 in the district time zone.
- **FR-R3** Teacher statuses: Not started, In progress, Submitted, Overdue,
  Returned.
- **FR-R4** Teachers save drafts and submit. Submitted sections are locked.
- **FR-R5** The requester can return a section with a comment. Each return
  and resubmission is audited.
- **FR-R6** Reminders go out 3 days before the due date, on the due date,
  and when overdue. The requester gets the overdue notice.

### 9. Scanned report vault (new)

#### 9.1 Concepts

- **Document:** one scanned report, owned by the supervisor who uploaded
  it. It holds one or more pages stored as one PDF, plus metadata.
- **Version:** replacing a document's file creates a new version. Earlier
  versions are kept.
- **Share:** a view grant from the owner to a recipient. In v1 the only
  recipient is the Cluster Head of the owner's cluster.
- **Report type:** a district-configured list, for example visit report,
  inspection checklist, signed acknowledgement, or incident report.
  **[Confirm]** the list (Q13).

#### 9.2 Upload and capture

- **FR-D1** Supervisors upload PDF, JPEG, PNG, HEIC, or TIFF files. Default
  limits: 25 MB per file and 50 pages per document, configurable by admin.
- **FR-D2** Several images can be uploaded as one document. The server
  combines them into a single PDF in the chosen page order.
- **FR-D3** On phones, the camera captures multi-page scans with page
  edge detection, crop, deskew, contrast enhancement, reorder, and delete
  before upload. Pages are combined and compressed on the device.
- **FR-D4** Required metadata: title, school, report type, report date.
  Optional: teacher, linked evaluation, notes, tags.
- **FR-D5** A supervisor can choose only schools they are or were assigned
  to. The report date must fall inside one of their assignment windows for
  that school, as in FR-AS6. The optional teacher must belong to that school
  on the report date.
- **FR-D6** Uploads are chunked, resumable, and idempotent on a
  client-generated key, so they work with the offline queue (FR-PW4) and
  never duplicate on retry.
- **FR-D7** If the owner uploads a file whose checksum matches one of their
  existing documents, they are warned before saving.
- **FR-D8** The server generates thumbnails and a page preview after the
  file passes scanning (FR-FS3).

#### 9.3 Access and isolation

- **FR-D10** Documents are private by default. Until shared, only the owner
  can see one.
- **FR-D11** No other supervisor can see, list, search, count, or download
  another supervisor's document. This applies to supervisors on the same
  school, to the supervisor who takes over a school after reassignment, and
  to supervisors in other clusters. A request for such a document by ID
  returns 404, and the denial is audited.
- **FR-D12** Access is decided on the server on every request: the user is
  the owner, or holds an active share. All document queries go through one
  scoped repository that always applies this filter. Listings, search,
  dashboard counts, exports, realtime events, and notifications use the
  same filter.
- **FR-D13** Files are served only through the API, after the access check,
  using signed URLs that last 5 minutes and are bound to the requesting
  session. A URL passed to another user or used after sign-out fails. There
  are no public buckets and no direct storage URLs.
- **FR-D14** Teachers have no access to documents in v1, including
  documents about them. **[Confirm]** (Q17).
- **FR-D15** District Admins have no routine access to document content.
  They see storage totals and counts per cluster for capacity planning.
  Content access exists only for legal or data-subject requests: it needs a
  written reason and approval by a second admin, lasts at most 24 hours, is
  audited as critical, and the owner is notified. **[Confirm]** (Q15).
- **FR-D16** Document responses are sent with `Cache-Control: private,
  no-store`. The service worker never caches documents shared with the
  user. The only documents stored on the device are the owner's own
  unsent uploads, which are removed after the server confirms them.

#### 9.4 Sharing

- **FR-D20** The owner shares a document with the Cluster Head of their
  cluster. The share targets the cluster's Cluster Head role, so after a
  vacancy reassignment (FR-AS8) the new Cluster Head sees it and the
  previous one loses access. This change is audited.
- **FR-D21** The owner can share several documents at once and add a
  message. The recipient is notified in-app, by email, and by push, subject
  to their preferences.
- **FR-D22** Share status: Shared, Viewed (first view time recorded),
  Acknowledged (optional comment), or Returned (comment required, for
  example "re-scan page 3; it is unreadable").
- **FR-D23** A returned document goes back to the owner, who uploads a new
  version and shares again. Each return and resubmission is audited.
- **FR-D24** Before acknowledgement, the owner can revoke a share. After
  acknowledgement the document is locked as a record: the owner cannot
  delete or revoke it. A correction is a new version with a required reason,
  and the earlier version stays visible to the recipient.
- **FR-D25** Recipients cannot share a document onward.
- **FR-D26** Supervisor-to-supervisor sharing is not available in v1. If
  the district approves it (Q12), it will be an explicit per-document,
  view-only, expiring grant to a named user, audited and revocable. Access
  will never come from a shared school or cluster.
- **FR-D27** Downloads and in-app views carry a watermark with the viewer's
  name, staff ID, and time on every page, applied when the file is served.
  The stored original is unchanged. **[Confirm]** (Q16).

#### 9.5 Lifecycle and retention

States: Uploading → Scanning → Private → Shared → Acknowledged or Returned.
Side states: Quarantined, Deleted.

- **FR-D30** The owner can delete their own unshared or revoked document.
  Deletion is soft for 30 days, during which the owner can restore it. After
  that the file and all versions are purged. Each step is audited.
- **FR-D31** The Cluster Head can archive an acknowledged document. It
  leaves the active inbox and stays searchable.
- **FR-D32** Documents are kept for a district-configured period, default 7
  years from the report date. **[Confirm]** (Q14). A purge job removes
  expired documents and writes an audit entry per document.
- **FR-D33** When a supervisor is deactivated, their documents are kept.
  Shared documents stay with the Cluster Head. Unshared documents stay
  inaccessible to everyone except through FR-D15.
- **FR-D34** A school reassignment never moves documents. The new supervisor
  starts with none.
- **FR-D35** On erasure (section 13.1), the owner is anonymized and the
  documents remain as institutional records.

#### 9.6 Lists and search

- **FR-D40** Supervisor: "My documents", filtered by school, type, date,
  and share status, with drafts and returned items first.
- **FR-D41** Cluster Head: "Shared with me" inbox, filtered by supervisor,
  school, type, date, and status, with unacknowledged items first and
  overdue acknowledgement flagged after a configurable number of days
  (default 7).
- **FR-D42** Search in v1 covers metadata only. Full-text search over OCR
  text is a post-v1 item, and its index must apply the FR-D12 filter.

#### 9.7 Storage and audit

- **FR-D50** Files are encrypted at rest with a key per file (envelope
  encryption). Keys are stored outside the database and file store.
- **FR-D51** Storage keys are random identifiers. Paths contain no names,
  school codes, or titles.
- **FR-D52** Storage quota per supervisor, default 2 GB. District quota
  alert at 80%.
- **FR-D53** Upload rate limit, default 60 files per user per hour.
- **FR-D54** Document files are included in backups with the same RPO and
  RTO as the database.
- **FR-D55** Audited actions: upload, new version, view, download, share,
  revoke, acknowledge, return, delete, restore, purge, metadata edit,
  quarantine, admin content access, and every denial.
- **FR-D56** Each version stores a SHA-256 checksum, recorded in its audit
  entry and verified on restore.

### 10. Realtime, notifications, offline, and files

#### 10.1 File service (new)

One service stores every file: form attachments (FR-F5) and scanned
documents (section 9).

- **FR-FS1** Every file has a record with storage key, MIME type, size,
  SHA-256, scan status, and encryption key reference.
- **FR-FS2** The file type is detected from content, not the extension.
  Mismatches are rejected. PDFs are sanitized: JavaScript, embedded files,
  forms, and external links are removed. Encrypted PDFs are rejected with a
  clear message. Images are re-encoded and EXIF data, including GPS, is
  removed.
- **FR-FS3** Every file is virus-scanned before it can be served. Status:
  Pending, Clean, or Quarantined. A quarantined file is never served; the
  uploader and admins are notified.
- **FR-FS4** Downloads need an access check by the owning feature, then a
  session-bound signed URL as in FR-D13. Responses set
  `X-Content-Type-Options: nosniff`, and inline previews use a sandboxed
  Content Security Policy.

#### 10.2 Realtime

- **FR-RT1** Live updates over WebSocket, with SSE fallback, for assignment
  changes, evaluation and request status changes, document share status
  changes, user activation or deactivation, and new notifications.
- **FR-RT2** Each user receives only events in their scope. Scope is
  enforced at the broadcaster, not only in the client. Document events use
  the FR-D12 filter.
- **FR-RT3** Reconnect with backoff, then refetch the current state.
- **FR-RT4** v1 runs the broadcaster in the single API process. Presence
  indicators are removed from v1 to limit personal data processing.

#### 10.3 Notifications

- **FR-N1** In-app notification center with read and unread state.
- **FR-N2** Email via Gmail for login codes, invitations, password resets,
  request reminders, overdue notices, assignment changes, submissions, and
  document shares, returns, and acknowledgements.
- **FR-N3** Web Push for users who grant permission.
- **FR-N4** Users choose optional notification types per channel. Security
  mail is always sent.
- **FR-N5** Every outbound message is logged with recipient, template,
  status, provider message ID, and attempts.
- **FR-N6** Mail queue priority: security mail, then invitations, then
  reminders, then informational notices. A daily counter alerts at 80% of
  the provider quota.
- **FR-N7 (new)** Notification and email text about a document includes
  its title and school only. It never includes the file or page images.

#### 10.4 Offline (PWA)

- **FR-PW1** Installable on Android Chrome and on iPhone Safari via Add to
  Home Screen.
- **FR-PW2** Responsive from 360px width upward.
- **FR-PW3** Cached for offline use: the user's assigned schools and
  teachers, active form definitions, their own drafts, and metadata for
  their own documents.
- **FR-PW4** Drafts save to IndexedDB. Offline submissions and document
  uploads are queued and sent in order.
- **FR-PW5** Each queued item carries a client-generated idempotency key.
  The server confirms each one, so a replay never creates a duplicate.
- **FR-PW6** If the server version changed since the client last read it,
  both versions are shown and the user chooses. The server never overwrites
  silently.
- **FR-PW7** Visible connection state and a count of queued items.
- **FR-PW8** Persistent storage is requested at install. The user is warned
  if a queued item is at risk.
- **FR-PW9 (changed)** Photos and scans are compressed on the device before
  queuing. The offline file queue holds up to 20 items or 200 MB per device,
  whichever comes first.
- **FR-PW10** Camera access for photo attachments and document scanning.
- **FR-PW11 (new)** Queued items carry the device time of capture. The
  server stores both device time and receipt time and flags skew over 24
  hours to the user and in the audit entry.
- **FR-PW12 (new)** Sign-out clears IndexedDB, Cache Storage, and the
  pending queue. If unsent items exist, the user is warned and must confirm.

### 11. Audit and logging

- **FR-L1** Each audit entry records: sequence number, actor ID, actor
  role, cluster ID, action, entity type, entity ID, before-values,
  after-values, IP address, user agent, UTC timestamp, previous entry hash,
  and this entry's hash.
- **FR-L2 (changed)** Logged actions: all logins, successful or failed; OTP
  issue and verification; lockouts and unlocks; every create, update,
  deactivation, and transfer; every assignment change; every evaluation,
  amendment, cancellation, and request status change; every return; every
  document action in FR-D55; every export; every permission denial; every
  break-glass action; every admin support view.
- **FR-L3** The application database user has INSERT and SELECT on the
  audit table only. No UPDATE or DELETE.
- **FR-L4** A daily job recomputes the hash chain. Any break raises a
  critical alert to all admins and appears on the admin dashboard.
- **FR-L5** Audit viewer with search and filters by actor, entity, action,
  and date. Exporting the audit log is itself audited.
- **FR-L6** Audit rows store user IDs, not names. Before and after values
  hold identifiers and changed fields, not full personal records. Document
  entries hold the document ID and checksum, never titles or content.
- **FR-L7** Application logs are separate from audit: structured JSON with
  request IDs. Errors include stack traces but no personal data, secrets,
  or signed URLs.
- **FR-L8** Audit retention is 7 years by default, configurable by the
  district within legal limits.
- **FR-L9 (new)** Supervisors can see the access history of their own
  documents: who viewed or downloaded each one, and when.

### 12. Reporting, search, and export

- **FR-RP1** Global search across schools, teachers, supervisors,
  evaluations, and document metadata within the user's scope.
- **FR-RP2** Dashboards by role:
  - Admin: clusters, school and teacher counts, overdue requests, audit
    chain status, storage use, quarantined files.
  - Cluster Head: unassigned schools, evaluation progress by school,
    supervisor workload, overdue requests, schools without a contact
    teacher, documents awaiting acknowledgement.
  - Supervisor: upcoming visits, drafts, completed evaluations, returned
    documents.
  - Teacher: pending requests with due dates.
- **FR-RP3** Standard reports: evaluation status by school, by supervisor,
  and by period; request completion; assignment history; raw answers by
  form; **(new)** documents shared by supervisor, school, type, and period.
  Export to PDF and Excel.
- **FR-RP4** Every export is audited with the requester, parameters, and
  row count.
- **FR-RP5 (new)** A Cluster Head can download a ZIP of documents shared
  with them, with a 200-file limit per export. It runs as a background job,
  each file is watermarked, and the export is audited with the list of
  document IDs.

### 13. Administration, privacy, and erasure

- **FR-AD1 (changed)** Admin settings: district name and logo, time zone,
  default and enabled locales, mail sender identity, session timeout, OTP
  settings, audit retention, document report types, document retention,
  upload limits and quotas, notification defaults.
- **FR-AD2** Admin sees locked accounts and failed login attempts.
- **FR-AD3 (changed)** Read-only support view of a user's screens. Requires
  a reason, lasts at most 30 minutes, is fully audited, and is shown to the
  user at their next login. It hides document content, attachments, and
  free-text answers.
- **FR-AD4** Personal data access and erasure requests are handled by
  admin under a documented procedure.
- **FR-AD5 (new)** Deactivating or demoting an admin is blocked if fewer
  than two active admins would remain.

#### 13.1 Erasure

- Erasure anonymizes the user's name, email, phone, and staff ID, and keeps
  the user ID so audit references stay valid.
- Evaluations, submissions, and documents remain, linked to the anonymized
  user ID, as institutional records.
- **[Confirm]** The district decides whether evaluation records and scanned
  documents about erased teachers are kept or anonymized (Q8).

### 14. Multilingual and localization

- **FR-I1** No hard-coded user-facing strings. All text is translatable.
- **FR-I2** The district sets default and enabled locales. **[Confirm]**
  The launch language list (Q1).
- **FR-I3** Users choose their locale. The browser language applies until
  a choice is made.
- **FR-I4** Right-to-left layout, including mirrored navigation and form
  alignment.
- **FR-I5** Dates, numbers, and currencies are formatted by locale. Storage
  is UTC and ISO dates.
- **FR-I6** Form content, report type names, and system emails are
  translated. User-entered text, including document titles, is stored as
  entered. No machine translation.
- **FR-I7** Search normalizes diacritics and Arabic presentation forms.
  Exports and watermarks embed fonts that cover every enabled script.
- **FR-I8** CSV and Excel import accepts UTF-8 and UTF-8 with BOM, and
  rejects other encodings with a clear error.

### 15. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | HTTPS and HSTS. CSRF protection. Secure, HTTP-only, same-site cookies. Server-side validation. Parameterized queries only. Scope enforced on every query. Files handled per section 10.1. API rate limits: 300 requests per user per minute and 1,000 per IP per minute, with stricter limits on auth and upload endpoints. Security scan before each release; external penetration test before go-live, covering access to other users' documents by ID. |
| Isolation | Document access follows FR-D12 in every code path. A permission-matrix test covers every document endpoint with every role, including a second supervisor on the same school. |
| Privacy | Data visible only within scope. No third-party analytics. Minimal personal data in audit. Location captured only with permission, and only at submission. EXIF removed from uploads. |
| Performance | First load under 2 s on 4G. List queries under 300 ms at 10,000 teachers and 200,000 documents. Realtime delivery under 2 s. A 10-page scan uploads in under 30 s on 4G. |
| Availability | 99.5% monthly target during school hours. Single-instance deployment in v1. |
| Recovery | RPO 24 hours. RTO 8 hours. Encrypted daily backups of the database and file storage, kept 30 days, in separate storage. Monthly restore test recorded, including a checksum check on sampled files. |
| Scale per district | Up to 500 schools, 10,000 teachers, 500 supervisors, 5 concurrent Cluster Heads per cluster, and 1 TB of documents. |
| Accessibility | WCAG 2.1 AA: keyboard navigation, labels, contrast, screen-reader support, RTL. |
| Browsers | Current and previous Chrome, Edge, Firefox, and Samsung Internet. Safari on iOS 16.4 and later. |
| Observability | Health endpoint and error tracking. Metrics for login failures, mail queue depth, quota usage, realtime connections, audit chain status, scan queue depth, quarantined files, storage use, and document access denials. |
| Maintainability | One service layer for all business rules. Validation schemas shared between client and server. No duplicated rule logic. |

### 16. Architecture and data model

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic, Pydantic.
- **Database:** MySQL 8 with InnoDB and utf8mb4 (utf8mb4_unicode_ci).
- **Frontend:** React and TypeScript, Vite, TanStack Query, schema-based
  forms, i18next.
- **Realtime:** WebSocket with SSE fallback; in-process broadcaster in v1.
- **Jobs:** Database-backed job table with one worker process, for mail,
  reminders, imports, exports, audit verification, virus scanning, PDF
  assembly and sanitization, thumbnails, and retention purges.
- **Mail:** Gmail API over OAuth2, for the district's Workspace account,
  with the priority queue and quota counter.
- **Files:** S3-compatible object storage (MinIO for on-premise), private
  bucket, per-file envelope encryption, ClamAV scanning, session-bound
  signed URLs.
- **Scanning on device:** client-side edge detection and image cleanup in
  a Web Worker; PDF assembly on device for camera scans and on the server
  for uploaded images.
- **PWA:** Workbox service worker, IndexedDB for offline data, Web Push via
  VAPID.
- **Deployment:** Docker Compose per district: API, worker, MySQL, object
  storage, ClamAV, and a TLS reverse proxy. Backups to separate storage.

#### 16.1 Core tables

| Table | Key columns |
|---|---|
| districts | Single row: name, default_locale, time_zone, settings |
| locales, ui_strings, form_translations | Locale codes and translated strings |
| users | id, role, email, staff_id, name, locale, status, version, failed_otp_count, locked_until |
| otp_codes | user_id, purpose, code_hash, expires_at, used_at |
| sessions | user_id, token_hash, created_at, last_seen_at, ip, user_agent, revoked_at |
| clusters | id, name, code, cluster_head_id, status, version |
| schools | id, cluster_id, school_code, name, details JSON, status, version |
| school_contacts | id, school_id, teacher_id, start_date, end_date |
| teachers | id, user_id, school_id, status, version |
| teacher_transfers | id, teacher_id, from_school_id, to_school_id, moved_at, moved_by |
| supervisors | id, user_id, cluster_id, status, version |
| supervisor_cluster_moves (new) | id, supervisor_id, from_cluster_id, to_cluster_id, moved_at, moved_by |
| supervisor_assignments | id, supervisor_id, school_id, start_date, end_date, status, reason, version |
| form_definitions | id, code, subject_type, status |
| form_versions | id, form_definition_id, version, published_at, schema JSON, immutable |
| evaluations | id, form_version_id, subject_type, school_id, teacher_id, supervisor_id, status, visit_date, submitted_at, amended_at, version |
| evaluation_sections | id, evaluation_id, section_key, respondent, respondent_user_id, status, answers JSON, due_at, submitted_at, version |
| evaluation_amendments | id, evaluation_id, reason, prior_answers JSON, created_by, created_at |
| stored_files (new) | id, storage_key, mime_type, size, sha256, page_count, scan_status, key_ref, created_by, created_at |
| attachments (changed) | id, owner_type, owner_id, stored_file_id, uploaded_by |
| document_types (new) | id, code, status; names in translations |
| documents (new) | id, owner_supervisor_id, cluster_id, school_id, teacher_id, evaluation_id, document_type_id, title, report_date, notes, status, current_version_id, deleted_at, purge_after, version |
| document_versions (new) | id, document_id, version_no, stored_file_id, reason, client_key, device_time, created_at |
| document_shares (new) | id, document_id, recipient_kind (cluster_head_role), cluster_id, status, message, shared_at, first_viewed_at, acknowledged_at, returned_at, revoked_at, comment, version |
| document_access_grants (new) | id, document_id, grantee_user_id, reason, approved_by, expires_at; used only for FR-D15 |
| notifications | id, user_id, type, payload JSON, read_at, created_at |
| notification_preferences | user_id, type, channel, enabled |
| mail_queue | id, template, recipient, priority, status, provider_message_id, attempts, error, created_at |
| jobs | id, type, payload JSON, status, attempts, run_after, created_at |
| audit_log | seq, actor_id, actor_role, cluster_id, action, entity_type, entity_id, before JSON, after JSON, ip, user_agent, created_at, prev_hash, hash |

Indexes: `documents (owner_supervisor_id, status, report_date)`,
`document_shares (cluster_id, status, shared_at)`, and a unique key on
`document_versions (document_id, client_key)` for idempotent upload.

Offline submissions carry a client-generated idempotency key, so retries
are safe. Sync state lives only on the client, in IndexedDB.

### 17. Key workflows

1. **Login:** password, then emailed code, then session. Each step is
   audited.
2. **Assign:** conflict check, insert, audit entry, realtime event, and
   notification, in one transaction.
3. **Reassign:** end supervisor A's assignment and start supervisor B's, in
   one transaction. Open drafts need an explicit choice. Documents stay
   with A.
4. **School evaluation:** the supervisor starts a draft and completes
   supervisor sections. Teacher sections go to the contact teacher. The
   supervisor submits once all required sections are in or waived.
5. **Teacher section:** the teacher completes and submits. The requester
   can return it. Reminders run from the job table.
6. **Offline submit:** queued locally, sent in order with idempotency keys.
   Conflicts are shown to the user.
7. **Scan and share a report (new):** the supervisor scans pages with the
   camera or picks files, fills in metadata, and saves. The upload is
   queued if offline. The server scans and sanitizes the file, and it
   becomes Private. The supervisor shares it with the Cluster Head, who is
   notified, views it (recorded), and acknowledges or returns it. Every
   step is audited.
8. **Returned report (new):** the supervisor sees the return comment,
   uploads a new version, and shares again. The recipient sees both
   versions.

### 18. Acceptance criteria

Carried from v0.2:

- An unassigned supervisor gets 403 on a school's evaluations, and the
  denial is audited.
- Two Cluster Heads reassigning the same school at once: one succeeds, the
  other gets 409 with the current state.
- After a reassignment, history shows both supervisors with correct dates.
- A locked account cannot log in until unlocked, even with the correct
  password.
- A submitted evaluation cannot be edited. An amendment keeps prior answers
  and writes an audit entry.
- An audit row cannot be edited or deleted through the application. A
  manual database tamper is detected by the daily hash check.
- An offline draft survives an app restart and syncs once online, with no
  duplicate.
- A teacher gets 404 for another teacher's request, even when calling by
  ID.
- Break-glass 2FA reset requires server access, writes a critical audit
  entry, and notifies all admins.
- The mail queue sends OTP mail before reminders, even when the queue is
  full.
- Switching to an RTL locale mirrors the layout, and exported PDFs render
  every enabled script.

New in v0.3:

- Supervisors A and B are both assigned to school X. A uploads a document
  for X. B's document list, search, dashboard counts, and realtime events
  show nothing of it, and B gets 404 when requesting it by ID. The denial
  is audited.
- After school X is reassigned from A to B, B still cannot see any of A's
  documents.
- A signed download URL issued to A fails when used from B's session, from
  a signed-out session, or after 5 minutes.
- The Cluster Head cannot see A's document until A shares it. After a
  Cluster Head vacancy reassignment, the new Cluster Head sees shared
  documents and the previous one gets 404.
- A Cluster Head of another cluster gets 404 for a document shared within
  cluster 1.
- An acknowledged document cannot be deleted or revoked by its owner. A
  correction creates a new version and both versions stay visible to the
  recipient.
- An upload with a forged extension is rejected. A PDF with embedded
  JavaScript is stored without it. An image's GPS EXIF data is removed. The
  EICAR test file is quarantined and never served.
- A document upload queued offline and retried three times creates exactly
  one document.
- The admin support view of a supervisor shows no document content.
- Admin content access without a second admin's approval is refused.
- Signing out on a shared phone removes all cached data and queued files,
  after a warning if any are unsent.
- A deleted document can be restored for 30 days, then it is purged and the
  purge is audited.
- The restore test recovers document files whose checksums match their
  records.

### 19. Test strategy

Each test type runs at the cheapest point that still catches its defects.
Full suites do not run on every check-in.

| Level | When it runs | What it covers |
|---|---|---|
| Unit | On each change, touched modules only | Validators, OTP logic, conflict rules, form schema validation, locale formatting, hash computation, document state transitions |
| Permission matrix | On changes to auth, roles, scoping, or documents | Table-driven: every role against every endpoint, including cross-cluster, cross-school, and same-school second supervisor access to documents |
| Auth abuse | On changes to auth or mail | OTP brute force, lockout, rate limits, expired and reused codes |
| API integration | On merge to main | Real MySQL and object storage in containers: assign, reassign, conflicts, evaluations, amendments, sections, requests, returns, document upload, share, acknowledge, return, delete, restore |
| File safety | On changes to the file service | Type sniffing, PDF sanitization, EXIF removal, EICAR quarantine, size and page limits, signed URL binding and expiry |
| Audit integrity | On merge, and on any change to audited code | Each audited action yields one correct entry; hash chain verifies; a simulated tamper is detected |
| Offline sync | On changes to the sync module | Queue order, idempotent replay, conflict handling, storage eviction warning, resumable upload, sign-out wipe |
| Migrations | On each migration | Applied to a copy of production-shaped data; counts and constraints verified |
| Security scan | Before each release | Dependency audit and OWASP-based scan of a staging build |
| Penetration test | Before go-live, and after major changes to documents or auth | External test focused on access to other users' objects by ID, signed URL abuse, and upload attacks |
| Browser end-to-end | Before each release | Login with 2FA, assign-and-evaluate, teacher request, scan-and-share, on desktop and two mobile viewports |
| Accessibility | Before each release | Automated checks plus a keyboard pass on the four critical journeys |
| Localization | Before each release, and when a locale or form is added | Pseudo-locale pass, RTL pass, export and watermark font check |
| Device check | Before each release | Install, offline run, and camera scan on one Android device and one iPhone |
| Restore | Monthly | Latest backup restored to a scratch instance; row counts, audit chain, and sampled file checksums verified |
| Load | Before go-live, and after infrastructure change | Realtime connections, list queries, and concurrent uploads at target scale |

Test data comes from one shared fixture module. Nothing is copied between
tests.

### 20. Delivery phases

The product ships in six phases. Each phase ends in a usable release, so
the pilot district gets value early and later phases build on tested
foundations. Scope, exit criteria, and dependencies for each phase are in
[delivery-plan.md](delivery-plan.md).

| Phase | Name | Release |
|---|---|---|
| 1 | Foundation and district structure | Staging. Admins and Cluster Heads build the pilot district from imports. |
| 2 | Supervision core and scanned reports | Pilot 1: one cluster. Supervisors run evaluations online and scan and share reports. |
| 3 | Teacher participation | Pilot 1 extended to teachers in the pilot cluster. |
| 4 | Mobile, offline, and realtime | Pilot 2: all clusters in the pilot district. |
| 5 | Reporting, administration, and go-live | Production go-live in the pilot district. |
| 6 | After v1 | Backlog, ordered by district priority. |

### 21. Open questions

Each question must be answered before the phase shown.

1. **Languages (before Phase 1):** Which locales launch, and what is the
   default per district?
2. **Form content (before Phase 2):** Who supplies the fixed forms, and in
   what format? We need sections, questions, respondents, and any score
   fields.
3. **Scoring (before Phase 5):** Does the district need aggregate scores?
   If so, what are the rules?
4. **School and teacher fields (before Phase 1):** Confirm the required
   field list.
5. **Teacher email (before Phase 1):** Do all teachers have a usable
   personal email, or do some need a recorded verified contact?
6. **Gmail quota (before Phase 1):** Which Workspace plan does the district
   use, and what is its daily sending limit?
7. **Trusted devices (before Phase 1):** Is OTP on every login acceptable,
   or may a trusted device skip the code for a set period?
8. **Retention and erasure (before Phase 5):** Are evaluation records and
   scanned documents about erased teachers kept, or anonymized?
9. **Admin count (before Phase 1):** Can the district name at least two
   admins?
10. **Contact teacher model (before Phase 3):** Confirm that each school
    designates one contact teacher at a time.
11. **Pilot (before Phase 2):** Which district, which cluster for Pilot 1,
    and how many schools and users?
12. **Document recipients (before Phase 2):** Confirm that supervisors share
    scanned reports with their Cluster Head only. Is supervisor-to-supervisor
    sharing ever needed, for example during a handover?
13. **Report types (before Phase 2):** Which report types do supervisors
    upload, and is any metadata required beyond title, school, type, and
    date?
14. **Document retention (before Phase 2):** How long must scanned reports
    be kept? Is the 7-year default acceptable?
15. **Admin access to documents (before Phase 2):** Is two-admin-approved
    content access for legal and data-subject requests acceptable, or must
    admins have no content access at all?
16. **Watermarks (before Phase 2):** Are viewer watermarks on views and
    downloads acceptable?
17. **Teacher visibility (before Phase 3):** Should teachers ever see
    scanned reports about themselves or their school?
18. **Storage (before Phase 1):** Will the district host object storage
    on-premise, or use a cloud provider? Is there a data residency rule?
