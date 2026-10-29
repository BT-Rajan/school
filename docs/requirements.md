# School Cluster Evaluation System: Requirements v0.4

Oct 29, 2026 · Supersedes v0.3 (see git history) and v0.2
([archived](archive/School_Cluster_Evaluation_System_Requirements_v0.2.docx))

This revision applies the district's answers to the v0.3 open questions.
The main changes:

- Supervisors submit scanned reports to the **District Admins**, who
  receive every report and may forward one to a Cluster Head.
- Forms are **built by the implementation team as drafts** and **published
  by a District Admin** with a start and end date.
- Every form and scanned report carries a **ministry report ID and version
  ID**.
- **Google Authenticator** can be used instead of emailed login codes.
- **Nothing is ever hard-deleted.**

The phased plan is in [delivery-plan.md](delivery-plan.md).

New requirements are marked **(new)** and changed ones **(changed)**. Items
marked **[Confirm]** are still open and collected in section 21.

---

## Part A: District decisions

### A.1 Decisions received on Oct 29, 2026

| # | Question | District answer | Effect on this specification |
|---|---|---|---|
| D1 | Languages | English is the default. Users can switch to Arabic at any time. | FR-I2, FR-I3: language switch on every screen, including login. Arabic uses a right-to-left layout. |
| D2 | Teacher fields | District, cluster ID, school ID, teacher name, teacher ID, designation, subjects, classes, experience, qualification, plus 8 to 10 more fields to come | FR-T1 lists the fixed fields. FR-T5 lets the admin add up to 15 custom fields without code changes. |
| D3 | Teacher email | All teachers have email. | FR-A10 is now checked when the invitation is accepted. No fallback contact is needed. |
| D4 | Mail provider | Gmail free tier for now, to be upgraded as use grows | FR-N6, FR-N8: quota of about 500 recipients a day by default, quota planning, daily digests, and a switchable mail provider. |
| D5 | Login second factor | Google Authenticator as an alternative to email codes | FR-A12 to FR-A15: authenticator app codes (TOTP) and recovery codes. |
| D6 | Two admins | Yes | FR-AD5 stays: at least two active admins. |
| D7 | File storage | On the district's own servers | MinIO on the district's servers. Backups go to a separate server (section 16). |
| D8 | Forms | We build each form and leave it in draft. A District Admin publishes it with a start and end date in D/MM/YYYY format. | New Form Author role, form builder, and publishing rules (sections 8.2 and 8.3). |
| D9 | Users | 2 District Admins, 30 supervisors, about 180 teachers | Sizing in section 15. |
| D10 | Report recipients | Reports go to the District Admins, who receive all of them. Supervisors track their own reports on a dashboard. | Section 9.4 recipient is changed to District Admins, with forwarding by an admin. FR-D44 adds the supervisor dashboard. |
| D11 | Report types | The ministry publishes them. Each needs a report ID and version ID, and a new form is built for each version. | New ministry report catalog (section 8.1). Every form version and scanned report is linked to a catalog entry. |
| D12 | Document retention | 7 years | FR-D32 |
| D13 | Admin access to documents | Admins have access. | FR-D15: full access, audited. No second-admin approval. |
| D14 | Watermarks | Yes | FR-D27 |
| D15 | Contact teacher | One per school at a time | Section 5 unchanged |
| D16 | Teacher access to reports | No | FR-D14: teachers never see scanned reports. |
| D17 | Scoring | The formula will be supplied separately. | Section 8.5: score fields are stored now. The formula is added when it arrives. |
| D18 | Erasure | No full erasure; soft delete only | Section 13.1: nothing is hard-deleted. The anonymization requirements are removed. |

### A.2 Interpretations to confirm

- **Who builds forms.** "We build the form" is read as the implementation
  team, through a Form Author role that sees forms only and no district
  data. If District Admins should also build forms, the same builder can be
  opened to them (Q6).
- **How Cluster Heads get reports.** "Sharing is through the District
  Admin" is read as: supervisors submit only to the District Admins, and an
  admin may forward a report to the Cluster Head of the school's cluster.
  Supervisors never share directly, and reports are never forwarded to
  another supervisor (Q5).
- **Admin access to drafts.** "Admins should have access" is read as access
  to every document, including drafts a supervisor has not yet submitted.

---

## Part B: Requirements

### 1. Purpose

Give a district one system to organize schools into clusters, assign
supervisors to visit them, collect evaluations through ministry report
forms, and receive scanned visit reports. Every change is tracked in a
tamper-evident log, status updates reach users in real time, phones work
offline, and no supervisor can see another supervisor's work.

### 2. Scope and deployment

- One deployment per district, on the district's own servers, with its own
  database, file storage, secrets, and mail account.
- A deployment holds multiple clusters. A supervisor belongs to one cluster
  at a time.
- PWA only. No native store apps in v1.
- The servers must be reachable from the internet over HTTPS with a
  publicly trusted certificate. Phones in the field need this to sign in,
  install the PWA, and receive push notifications.
- Out of scope in v1: machine translation of user text, OCR of scanned
  reports, payments, timetables, student records, attendance, and
  cross-district reporting.

### 3. Users and roles

| Role | Created by | Scope | Core capabilities |
|---|---|---|---|
| District Admin | Installer; at least two required | District | Clusters and Cluster Heads, system settings, reference lists and custom fields, mail settings, audit viewer, account recovery. Reviews and publishes forms. Receives every scanned report, acknowledges or returns it, and may forward it. Full access to documents, audited. |
| Form Author (new) | Installer, through the server CLI | Forms and ministry report catalog only | Builds forms and catalog entries as drafts, previews them, and hands them to the admins for publishing. Sees no schools, users, evaluations, or documents. |
| Cluster Head | District Admin | Own cluster | Schools, teachers, supervisors; assign, unassign, reassign; send requests; progress and reports. Sees scanned reports only when an admin forwards them. |
| Supervisor | Cluster Head | Assigned schools; own work | Completes evaluations; views assigned schools and their teachers; uploads scanned reports and submits them to the District Admins; tracks own reports on a dashboard. |
| Teacher | Cluster Head or import | Own school and own requests | Completes requests; acts as contact teacher where designated; sees own submissions. No access to scanned reports. |

**Role rules**

- A school belongs to exactly one cluster. A teacher belongs to exactly one
  school.
- Each school has at most one designated contact teacher at a time.
- A school can have several supervisors over time, and zero or more active
  ones at any moment.
- Supervisors are isolated from each other. Being assigned to the same
  school grants no access to another supervisor's evaluations,
  attachments, or documents.
- **(changed)** Users and records are deactivated or soft-deleted, never
  hard-deleted (section 13.1).

### 4. Authentication and account security

- **FR-A1** Email and password login.
- **FR-A2 (changed)** A second factor is required on every login. The user
  chooses either an emailed code or an authenticator app code (FR-A12).
- **FR-A3** Lock the account for 15 minutes after 5 failed second-factor
  codes, or until an admin unlocks it. The lock applies to both methods.
- **FR-A4** Limit email code requests to 3 per account per 10 minutes and
  30 per IP per hour.
- **FR-A5** Password reset always uses an emailed code. A user with an
  authenticator must also enter an authenticator code or a recovery code.
- **FR-A6** Idle timeout of 12 hours. Forced sign-out on role change or
  deactivation.
- **FR-A7** Passwords hashed with Argon2id. Email codes and recovery codes
  hashed with HMAC.
- **FR-A8** Users can view active sessions and revoke any of them.
- **FR-A9** Break-glass 2FA reset: a server-side CLI command that requires
  confirmation, writes a critical audit entry, and emails all other admins.
- **FR-A10 (changed)** Every user has an email address. It is verified when
  the invitation is accepted.
- **FR-A11** Password policy: at least 10 characters, checked against a
  list of known breached passwords. No forced periodic rotation.

Email codes:

- 6 digits, valid 10 minutes, single use, stored hashed.

Authenticator app (new):

- **FR-A12** Users can enroll an authenticator app such as Google
  Authenticator (TOTP, RFC 6238: 6 digits, 30-second step). Enrollment
  shows a QR code and a manual key, and is confirmed by entering a valid
  code. One step of clock drift either way is accepted. A code that has
  already been used is rejected for the rest of its window.
- **FR-A13** TOTP secrets are encrypted at rest with a key held outside
  the database.
- **FR-A14** At enrollment the user receives 10 single-use recovery codes,
  shown once and stored hashed. The user can regenerate them, which
  invalidates the old ones.
- **FR-A15** If a user loses their phone, they sign in with a recovery
  code, or a District Admin resets them to email codes. The reset is
  audited and the user is told by email. Users can switch methods after
  re-entering their password and a current code.
- **FR-A16** District Admins and Form Authors must use an authenticator
  app, so they never depend on mail delivery. Other users may choose either
  method. **[Confirm]** (Q11).

### 5. Clusters, schools, and contact teachers

- **FR-S1** Admin creates, edits, and deactivates clusters. Each has a
  name, a cluster ID, and one Cluster Head.
- **FR-S2** Cluster Head creates, edits, and deactivates schools. Required:
  name, school ID (unique in the district), cluster, address, type, medium
  of instruction, contact details. **[Confirm]** the school field list
  (Q2). The admin can add custom fields (FR-T5 applies to schools too).
- **FR-S3** Search and filter by name, ID, status, supervisor, and contact
  teacher, with pagination.
- **FR-S4** Import schools from CSV or Excel, with a preview and per-row
  errors before commit. Idempotent on school ID.
- **FR-S5** Export school lists to CSV or Excel, including the district
  code and cluster ID.
- **FR-S6** Cluster Head designates or changes a school's contact teacher.
  The previous contact teacher's open school-level requests move to the new
  one, with notification.
- **FR-S7** A school cannot be deactivated while it has active assignments.
  Open evaluations are frozen, not deleted. Documents linked to it are kept.
- **FR-S8** Schools with no active supervisor are flagged on the Cluster
  Head dashboard.

### 6. Teachers and supervisors

- **FR-T1 (changed)** Cluster Head creates, edits, searches, and
  deactivates teachers. Fields:

  | Field | Rule |
  |---|---|
  | District | Set by the deployment; shown and exported |
  | Cluster ID | Taken from the school; never typed in |
  | School ID | Required; must exist in the cluster |
  | Teacher ID | Required; unique in the district |
  | Teacher name | Required; stored as entered, English or Arabic |
  | Email | Required; verified at invitation |
  | Designation | Required; one value from an admin-managed list |
  | Subjects | Required; one or more values from an admin-managed list |
  | Classes | Required; one or more values from an admin-managed list |
  | Experience | Required; total years of teaching experience with the date it was recorded, so the current figure can be shown |
  | Qualification | Required; one or more values from an admin-managed list, each with an optional year |

- **FR-T2** Import teachers from CSV or Excel, idempotent on teacher ID.
  List values can be given in English or Arabic. Each new valid row queues
  an invitation, sent within the daily mail budget (FR-N8).
- **FR-T3** Transfer a teacher to another school in the same cluster. The
  transfer is recorded with dates, under the rules in 6.1.
- **FR-T4** The invitation link sets the password and enrolls the second
  factor. It expires in 72 hours and is single use.
- **FR-T5 (new)** Custom fields: the District Admin adds up to 15 extra
  fields each for teachers and schools, with no code change. Each field has
  a type (text, number, date, single choice, multiple choice, yes/no),
  English and Arabic labels, a required flag, and validation. Custom fields
  appear in forms, imports, exports, filters, and the audit log. A retired
  field is hidden but its data is kept.
- **FR-T6 (new)** Reference lists for designations, subjects, classes, and
  qualifications are managed by the District Admin, with English and Arabic
  names. A value in use can be retired but not deleted.
- **FR-P1** Cluster Head creates, edits, searches, and deactivates
  supervisors. Required: staff ID (unique in the district), name, verified
  email.
- **FR-P2** Import supervisors from CSV or Excel, idempotent on staff ID.
- **FR-P3** Supervisor deactivation is blocked while active assignments
  exist. Their documents stay with the District Admins.
- **FR-P4** The supervisor profile shows current assignments, workload,
  evaluation counts, and report counts.

#### 6.1 Teacher transfer rules

- Open evaluations about the teacher stay with their supervisor.
- Open requests to the teacher stay with the teacher. The original
  requester keeps visibility.
- If the new school has a contact-teacher link to an open evaluation, the
  supervisor is notified and must confirm the link.

#### 6.2 Supervisor cluster transfer

- **FR-P5** Admin moves a supervisor to another cluster. All assignments in
  the old cluster must end first.
- The supervisor keeps read-only access to their own past evaluations and
  documents from the old cluster.

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
  Cluster Head. Supervisors and assignments are unaffected. Reports
  forwarded to the previous Cluster Head move to the new one.
- **FR-AS9** Draft transfer under FR-AS2 or FR-AS3 moves the evaluation
  draft only. Scanned documents never move between supervisors.

### 8. Ministry reports, forms, and evaluations

#### 8.1 Ministry report catalog (new)

The ministry publishes the reports supervisors must complete. Each has a
ministry report ID, and each revision has a version ID. The system builds a
new form for every version.

- **FR-MR1** The catalog holds one entry per ministry report version:
  report ID, version ID, title in English and Arabic, subject (School or
  Teacher), ministry publication date, and the ministry's source document
  (PDF) as a reference.
- **FR-MR2** The pair of report ID and version ID is unique. Catalog
  entries are created by Form Authors and published with their form (8.3).
- **FR-MR3** Every form version, evaluation, scanned report, export, and
  generated PDF shows the ministry report ID and version ID.
- **FR-MR4** When the ministry issues a new version, the Form Author
  creates a new catalog entry and a new draft form, starting from a copy of
  the previous version's form. The previous version stays valid until its
  end date.

#### 8.2 Building forms (changed)

- **FR-F1 (changed)** Forms are built by Form Authors in the in-app form
  builder. Cluster Heads and supervisors cannot create or edit forms.
- **FR-F2** A form is a schema of sections, questions, validation rules,
  conditional logic, and translations, stored as a versioned JSON document.
  It is linked to one ministry report version.
- **FR-F3** Each section has a respondent: supervisor or teacher. Teacher
  sections are delivered as requests.
- **FR-F4** Published form versions are immutable. An evaluation keeps the
  version it started with.
- **FR-F5** Question types: short text, long text, number with range,
  single choice, multiple choice, date, yes/no, rating scale, table (repeated
  rows of fixed columns), and file attachment (photo or PDF, through the
  file service in 10.1).
- **FR-F6** Conditional visibility based on earlier answers.
- **FR-F7 (changed)** Every question, option, and label has English and
  Arabic text. A form cannot be submitted for publishing until both
  languages are complete.
- **FR-F8** Score fields can be defined on questions, with weights (see
  8.5).
- **FR-F9 (new)** While a form is a draft, the Form Author can edit it
  freely. The builder validates the schema on every save, and the author
  can preview the form as each respondent, in each language, at phone and
  desktop width.
- **FR-F10 (new)** Form statuses: Draft, Ready for review, Scheduled,
  Active, Closed. A District Admin can return a form in review to Draft
  with comments.

#### 8.3 Publishing forms (new)

- **FR-PB1** A District Admin reviews a form in Ready for review, using the
  same preview as the Form Author, and publishes it with a start date and
  an end date.
- **FR-PB2** Dates are entered and shown in D/MM/YYYY format, for example
  5/11/2026. They are stored as ISO dates. The start date begins at 00:00
  and the end date finishes at 23:59, district time.
- **FR-PB3** The end date must be on or after the start date. The start
  date can be today or later. A form with a future start date is Scheduled
  and becomes Active automatically.
- **FR-PB4** Evaluations can be started only while a form is Active. A
  draft started inside the window can be submitted until the end date.
  After that it is frozen, unless an admin extends the end date.
- **FR-PB5** After publishing, an admin can extend the end date or close
  the form early, with a reason. Content cannot change. Each change is
  audited and notifies affected supervisors.
- **FR-PB6** By default only one version of a ministry report is Active at
  a time. If two versions' windows overlap, the admin must confirm it.
- **FR-PB7** Publishing a form publishes its catalog entry. From then on
  supervisors can choose that report version for scanned uploads.

#### 8.4 Evaluations

- **FR-E1** Two subjects: School and Teacher.
- **FR-E2** A School evaluation has supervisor sections and teacher
  sections. Teacher sections go to the school's contact teacher.
- **FR-E3** A Teacher evaluation has supervisor sections and teacher
  sections. Teacher sections go to the teacher being evaluated.
- **FR-E4** The supervisor starts an evaluation from an assigned school or
  teacher, picks an Active form, and saves drafts at any time, online or
  offline.
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
- **FR-E10** A supervisor sees only evaluations they own, including
  attachments. The Cluster Head and District Admins see all evaluations in
  their scope. A teacher sees only the sections addressed to them.
- **FR-E11** A supervisor can link their own scanned documents to an
  evaluation as supporting evidence. The link does not change who can see
  them.
- **FR-E12 (new)** A submitted evaluation can be generated as a PDF report
  in English or Arabic. The PDF shows the ministry report ID, version ID,
  evaluation ID, school, supervisor, and visit date. It is built from the
  stored answers every time it is requested, so amendments are reflected.

#### 8.5 Scoring (changed)

- **FR-SC1** Score fields are stored and exported from Phase 2.
- **FR-SC2** The district will supply the scoring formula. It will be
  stored as a versioned rule set attached to a form version, so a score can
  always be recalculated the same way.
- **FR-SC3** Scores are calculated on the server only, and shown on the
  evaluation, generated PDFs, dashboards, and exports. A change to the rule
  set never changes stored scores without a recorded recalculation.
- **[Confirm]** The formula document (Q9).

#### 8.6 Teacher requests

- **FR-R1** A request is a teacher-respondent section of an evaluation, or
  a standalone request type approved for the district, such as a school
  profile update. Standalone requests use published forms only.
- **FR-R2** Requests have a due date, instructions, and a reminder
  schedule. A due date ends at 23:59 district time.
- **FR-R3** Teacher statuses: Not started, In progress, Submitted, Overdue,
  Returned.
- **FR-R4** Teachers save drafts and submit. Submitted sections are locked.
- **FR-R5** The requester can return a section with a comment. Each return
  and resubmission is audited.
- **FR-R6** Reminders go out 3 days before the due date, on the due date,
  and when overdue. The requester gets the overdue notice.

### 9. Scanned report vault

#### 9.1 Concepts

- **Document:** one scanned report, owned by the supervisor who uploaded
  it. It holds one or more pages stored as one PDF, plus metadata.
- **Version:** replacing a document's file creates a new version. Earlier
  versions are kept.
- **Submission (changed):** the supervisor submits a document to the
  District Admins. All active District Admins receive it.
- **Forward (new):** a District Admin can give a Cluster Head view access
  to a submitted document.

#### 9.2 Upload and capture

- **FR-D1** Supervisors upload PDF, JPEG, PNG, HEIC, or TIFF files. Default
  limits: 25 MB per file and 50 pages per document, configurable by admin.
- **FR-D2** Several images can be uploaded as one document. The server
  combines them into a single PDF in the chosen page order.
- **FR-D3** On phones, the camera captures multi-page scans with page edge
  detection, crop, deskew, contrast enhancement, reorder, and delete before
  upload. Pages are combined and compressed on the device.
- **FR-D4 (changed)** Required metadata: ministry report ID and version ID
  (chosen from published catalog entries), school, and report date. The
  title defaults to the catalog title. Optional: teacher (required when the
  report's subject is Teacher), linked evaluation, notes, and tags.
- **FR-D5** A supervisor can choose only schools they are or were assigned
  to. The report date must fall inside one of their assignment windows for
  that school. The teacher must belong to that school on the report date.
- **FR-D6** Uploads are chunked, resumable, and idempotent on a
  client-generated key, so they work with the offline queue and never
  duplicate on retry.
- **FR-D7** If the owner uploads a file whose checksum matches one of their
  existing documents, they are warned before saving.
- **FR-D8** The server generates thumbnails and a page preview after the
  file passes scanning (FR-FS3).

#### 9.3 Access and isolation

- **FR-D10 (changed)** A document is a draft until the supervisor submits
  it. While it is a draft, the owner and the District Admins can see it.
- **FR-D11** No other supervisor can see, list, search, count, or download
  another supervisor's document. This applies to supervisors on the same
  school, to the supervisor who takes over a school after reassignment, and
  to supervisors in other clusters. A request for such a document by ID
  returns 404, and the denial is audited.
- **FR-D12** Access is decided on the server on every request. A user can
  see a document if they own it, are an active District Admin, or hold an
  active forward. All document queries go through one scoped repository
  that always applies this rule. Listings, search, dashboard counts,
  exports, realtime events, and notifications use the same rule.
- **FR-D13** Files are served only through the API, after the access
  check, using signed URLs that last 5 minutes and are bound to the
  requesting session. A URL passed to another user or used after sign-out
  fails. There are no public buckets and no direct storage URLs.
- **FR-D14 (changed)** Teachers never have access to scanned reports,
  including reports about them.
- **FR-D15 (changed)** District Admins have full access to every document,
  including drafts and earlier versions. Every view and download is
  audited, and the owner can see it in the access history (FR-L9).
- **FR-D16** Document responses are sent with `Cache-Control: private,
  no-store`. The service worker never caches documents that other users
  submitted. The only documents stored on a device are the owner's own
  unsent uploads, which are removed after the server confirms them.

#### 9.4 Submission, review, and forwarding (changed)

- **FR-D20** The supervisor submits one or more documents to the District
  Admins, with an optional message. All active District Admins are
  notified in-app, by email digest, and by push, subject to their
  preferences.
- **FR-D21** Statuses: Draft, Submitted, Viewed (time of first admin view
  recorded), Acknowledged (optional comment), Returned (comment required,
  for example "re-scan page 3; it is unreadable").
- **FR-D22** One admin's action counts for all admins. The inbox shows who
  viewed, acknowledged, or returned each document.
- **FR-D23** A returned document goes back to the supervisor, who uploads a
  new version and submits it again. Each return and resubmission is
  audited.
- **FR-D24** The supervisor can withdraw a submission before it is
  acknowledged. After acknowledgement the document is locked as a record. A
  correction is a new version with a required reason, and earlier versions
  stay visible to the admins.
- **FR-D25** A District Admin can forward a submitted document to the
  Cluster Head of the document's cluster, with an optional note. The
  forward is view-only and can be revoked. It is never possible to forward
  to a supervisor or a teacher. **[Confirm]** (Q5).
- **FR-D26** Supervisors cannot share documents with anyone directly.
- **FR-D27** Views and downloads by anyone other than the owner carry a
  watermark on every page with the viewer's name, staff ID, and the time,
  applied when the file is served. The stored original is unchanged.

#### 9.5 Lifecycle and retention (changed)

States: Uploading, Scanning, Draft, Submitted, Viewed, Acknowledged or
Returned. Side states: Quarantined, Withdrawn, Deleted.

- **FR-D30** The supervisor can delete their own draft or withdrawn
  document. Deletion is a soft delete: the document leaves the
  supervisor's lists, stays visible to the District Admins as Deleted, and
  can be restored by an admin. Nothing is hard-deleted.
- **FR-D31** District Admins can archive acknowledged documents. They
  leave the active inbox and stay searchable.
- **FR-D32** Documents are kept for at least 7 years from the report date.
  After that they are flagged Retention expired for admin review. They are
  never removed automatically.
- **FR-D33** When a supervisor is deactivated, their documents are kept and
  stay with the District Admins.
- **FR-D34** A school reassignment never moves documents. The new
  supervisor starts with none.

#### 9.6 Lists, search, and dashboards (changed)

- **FR-D40** Supervisor: "My reports", filtered by school, ministry report,
  version, date, and status, with drafts and returned items first.
- **FR-D41** District Admin: "Report inbox", filtered by supervisor,
  cluster, school, ministry report, version, date, and status, with
  unacknowledged items first. Items awaiting acknowledgement longer than a
  configurable number of days (default 7) are flagged.
- **FR-D42** Search in v1 covers metadata only. Full-text search over OCR
  text is a post-v1 item, and its index must apply the FR-D12 rule.
- **FR-D43** Cluster Head: "Forwarded to me", filtered the same way.
- **FR-D44 (new)** Supervisor dashboard, showing only their own work:
  - reports by status: draft, submitted, viewed, acknowledged, returned
  - returned reports with the admin's comment
  - coverage: for each Active ministry report, which assigned schools
    already have a submitted report and which do not
  - submissions per month
  - access history: which admin viewed or downloaded each report, and when

#### 9.7 Storage and audit

- **FR-D50** Files are encrypted at rest with a key per file (envelope
  encryption). Keys are stored outside the database and file store.
- **FR-D51** Storage keys are random identifiers. Paths contain no names,
  school IDs, or titles.
- **FR-D52** Storage quota per supervisor, default 2 GB. District quota
  alert at 80%.
- **FR-D53** Upload rate limit, default 60 files per user per hour.
- **FR-D54** Document files are included in backups with the same RPO and
  RTO as the database.
- **FR-D55** Audited actions: upload, new version, view, download, submit,
  withdraw, acknowledge, return, forward, revoke forward, delete, restore,
  archive, metadata edit, quarantine, and every denial.
- **FR-D56** Each version stores a SHA-256 checksum, recorded in its audit
  entry and verified on restore.

### 10. Files, realtime, notifications, and offline

#### 10.1 File service

One service stores every file: form attachments, ministry source
documents, and scanned reports.

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
  changes, evaluation and request status changes, report status changes,
  form publishing, user activation or deactivation, and new notifications.
- **FR-RT2** Each user receives only events in their scope. Scope is
  enforced at the broadcaster, not only in the client.
- **FR-RT3** Reconnect with backoff, then refetch the current state.
- **FR-RT4** v1 runs the broadcaster in the single API process. No presence
  indicators.

#### 10.3 Notifications and mail (changed)

- **FR-N1** In-app notification center with read and unread state.
- **FR-N2** Email for login codes, invitations, password resets, request
  reminders, overdue notices, assignment changes, submissions, form
  publishing, and report submissions, returns, and acknowledgements.
- **FR-N3** Web Push for users who grant permission.
- **FR-N4** Users choose optional notification types per channel. Security
  mail is always sent.
- **FR-N5** Every outbound message is logged with recipient, template,
  status, provider message ID, and attempts.
- **FR-N6 (changed)** Mail queue priority: security mail, then
  invitations, then reminders, then informational notices. The daily limit
  is a setting, default 500 recipients, matching Google's limit for a free
  Gmail account. Alerts go to admins at 80%.
- **FR-N7** Notification and email text about a report includes its
  ministry report ID, title, and school only, never the file or page
  images.
- **FR-N8 (new)** Mail budget rules for the free tier:
  - 40% of the daily limit is reserved for security mail. Other mail never
    uses it.
  - Reminders and informational notices are combined into one daily digest
    per user, sent at a configurable time.
  - Invitations from bulk imports are spread over several days within the
    budget. The admin sees the planned send dates.
  - When the non-reserved budget is used up, remaining non-security mail
    waits for the next day. Nothing is dropped.
- **FR-N9 (new)** The mail provider is a setting. Gmail API with OAuth2 is
  the default. Google Workspace or any SMTP relay can replace it by
  configuration, with no code change.

Expected load: about 212 users. If every user signs in daily with an
emailed code, that is about 212 messages a day, within the free limit.
Authenticator app use and daily digests leave room for growth. The first
bulk invitation of about 212 users is sent over two days.

#### 10.4 Offline (PWA)

- **FR-PW1** Installable on Android Chrome and on iPhone Safari via Add to
  Home Screen.
- **FR-PW2** Responsive from 360px width upward.
- **FR-PW3** Cached for offline use: the user's assigned schools and
  teachers, Active form definitions, the published report catalog, their
  own drafts, and metadata for their own documents.
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
- **FR-PW9** Photos and scans are compressed on the device before queuing.
  The offline file queue holds up to 20 items or 200 MB per device,
  whichever comes first.
- **FR-PW10** Camera access for photo attachments and document scanning.
- **FR-PW11** Queued items carry the device time of capture. The server
  stores both device time and receipt time and flags skew over 24 hours.
- **FR-PW12** Sign-out clears IndexedDB, Cache Storage, and the pending
  queue. If unsent items exist, the user is warned and must confirm.
- **FR-PW13 (new)** A queued evaluation for a form that closed while the
  device was offline is still accepted if its visit date falls inside the
  form's window. Otherwise the supervisor is told and the draft is kept.

### 11. Audit and logging

- **FR-L1** Each audit entry records: sequence number, actor ID, actor
  role, cluster ID, action, entity type, entity ID, before-values,
  after-values, IP address, user agent, UTC timestamp, previous entry hash,
  and this entry's hash.
- **FR-L2 (changed)** Logged actions: all logins, successful or failed;
  second-factor issue, verification, enrollment, reset, and recovery-code
  use; lockouts and unlocks; every create, update, deactivation, soft
  delete, restore, and transfer; every assignment change; every form
  draft save, review, return, publish, date change, and close; every
  evaluation, amendment, cancellation, and request status change; every
  return; every document action in FR-D55; every export; every permission
  denial; every break-glass action; every admin support view.
- **FR-L3** The application database user has INSERT and SELECT on the
  audit table only. No UPDATE or DELETE.
- **FR-L4** A daily job recomputes the hash chain. Any break raises a
  critical alert to all admins and appears on the admin dashboard.
- **FR-L5** Audit viewer with search and filters by actor, entity, action,
  and date. Exporting the audit log is itself audited.
- **FR-L6** Audit rows store user IDs, not names. Before and after values
  hold identifiers and changed fields, not full personal records.
- **FR-L7** Application logs are separate from audit: structured JSON with
  request IDs. Errors include stack traces but no personal data, secrets,
  TOTP secrets, or signed URLs.
- **FR-L8** Audit retention is 7 years by default, configurable by the
  district within legal limits.
- **FR-L9** Supervisors can see the access history of their own documents.

### 12. Reporting, search, and export

- **FR-RP1** Global search across schools, teachers, supervisors,
  evaluations, and document metadata within the user's scope.
- **FR-RP2** Dashboards by role:
  - Admin: clusters, school and teacher counts, overdue requests, audit
    chain status, report inbox summary, coverage by ministry report, forms
    by status with their windows, mail budget use, storage use, quarantined
    files.
  - Cluster Head: unassigned schools, evaluation progress by school,
    supervisor workload, overdue requests, schools without a contact
    teacher, reports forwarded to them.
  - Supervisor: upcoming visits, drafts, completed evaluations, and the
    report dashboard in FR-D44.
  - Teacher: pending requests with due dates.
- **FR-RP3** Standard reports: evaluation status by school, by supervisor,
  and by period; request completion; assignment history; raw answers by
  form; scanned reports by supervisor, school, ministry report, and period.
  Each report is filtered by ministry report ID and version where relevant.
  Export to PDF and Excel.
- **FR-RP4** Every export is audited with the requester, parameters, and
  row count.
- **FR-RP5** A District Admin can download a ZIP of reports, with a
  200-file limit per export. It runs as a background job, each file is
  watermarked, and the export is audited with the list of document IDs.

### 13. Administration and data retention

- **FR-AD1** Admin settings: district name, code, and logo; time zone;
  default and enabled languages; date format (default D/MM/YYYY); mail
  provider, sender identity, and daily limit; session timeout; second-factor
  rules; audit retention; reference lists; custom fields; document
  retention; upload limits and quotas; notification defaults and digest
  time.
- **FR-AD2** Admin sees locked accounts and failed login attempts.
- **FR-AD3** Read-only support view of a user's screens. Requires a reason,
  lasts at most 30 minutes, is fully audited, and is shown to the user at
  their next login.
- **FR-AD4** A District Admin can export everything held about one person
  (profile, assignments, evaluations, requests, documents) for an access
  request. The export is audited.
- **FR-AD5** Deactivating or demoting an admin is blocked if fewer than two
  active admins would remain.

#### 13.1 No hard deletion (changed)

- Users are deactivated, never deleted. A deactivated user cannot sign in;
  their records stay, linked to their user ID.
- Every other record is soft-deleted: it is marked deleted, hidden from
  normal lists, and can be restored by an admin. Restores are audited.
- No feature in the application removes data permanently. Records past
  their retention period are flagged for admin review.

### 14. Language and localization

- **FR-I1** No hard-coded user-facing strings. All text is translatable.
- **FR-I2 (changed)** English is the default language. Arabic is enabled at
  launch. More languages can be added by configuration.
- **FR-I3 (changed)** A language switch is on every screen, including the
  sign-in page. Switching takes effect immediately, without signing out or
  losing unsaved form input. The choice is saved to the user's profile and,
  before sign-in, on the device.
- **FR-I4** Arabic uses a right-to-left layout, including mirrored
  navigation, tables, form alignment, and generated PDFs.
- **FR-I5 (changed)** Dates are shown in D/MM/YYYY format in both
  languages. Numbers and dates use Western digits (0-9) in both languages
  by default. **[Confirm]** (Q7). Storage is UTC and ISO dates.
- **FR-I6** Forms, the report catalog, reference lists, custom field
  labels, and system emails have English and Arabic text. User-entered
  text is stored as entered. No machine translation.
- **FR-I7** Search normalizes diacritics and Arabic letter forms, so a
  search in either script finds names stored in that script. Exports and
  watermarks embed fonts that cover English and Arabic.
- **FR-I8** CSV and Excel import accepts UTF-8 and UTF-8 with BOM, and
  rejects other encodings with a clear error. Import templates are offered
  with English and Arabic column headings.
- **FR-I9 (new)** Emails are sent in the recipient's chosen language.

### 15. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | HTTPS and HSTS. CSRF protection. Secure, HTTP-only, same-site cookies. Server-side validation. Parameterized queries only. Scope enforced on every query. Files handled per section 10.1. API rate limits: 300 requests per user per minute and 1,000 per IP per minute, with stricter limits on auth and upload endpoints. Security scan before each release; external penetration test before go-live, covering access to other supervisors' documents by ID. |
| Isolation | Document access follows FR-D12 in every code path. A permission-matrix test covers every document endpoint with every role, including a second supervisor on the same school. |
| Privacy | Data visible only within scope. No third-party analytics. Minimal personal data in audit. Location captured only with permission, and only at submission. EXIF removed from uploads. |
| Performance | First load under 2 s on 4G. List queries under 300 ms at design scale. Realtime delivery under 2 s. A 10-page scan uploads in under 30 s on 4G. |
| Availability | 99.5% monthly target during school hours. Single-instance deployment in v1. |
| Recovery | RPO 24 hours. RTO 8 hours. Encrypted daily backups of the database, file storage, and encryption keys, kept 30 days, on a separate server. Monthly restore test recorded, including a checksum check on sampled files. **[Confirm]** an off-site copy (Q10). |
| Scale | Current district: 2 District Admins, 30 supervisors, about 180 teachers. Design scale per district, so growth needs no redesign: 500 schools, 10,000 teachers, 500 supervisors, 200,000 documents, 1 TB of files. |
| Accessibility | WCAG 2.1 AA in both languages: keyboard navigation, labels, contrast, screen-reader support, RTL. |
| Browsers | Current and previous Chrome, Edge, Firefox, and Samsung Internet. Safari on iOS 16.4 and later. |
| Observability | Health endpoint and error tracking. Metrics for login failures, second-factor method use, mail queue depth and budget, realtime connections, audit chain status, scan queue depth, quarantined files, storage use, and document access denials. |
| Maintainability | One service layer for all business rules. Validation schemas shared between client and server. No duplicated rule logic. |

### 16. Architecture and data model

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic, Pydantic.
- **Database:** MySQL 8 with InnoDB and utf8mb4 (utf8mb4_unicode_ci).
- **Frontend:** React and TypeScript, Vite, TanStack Query, schema-based
  forms, i18next.
- **Form builder:** a React editor that writes the same JSON schema the
  form renderer reads, so what the author previews is what users get.
- **Second factor:** TOTP (RFC 6238) with a standard library, plus emailed
  codes.
- **Realtime:** WebSocket with SSE fallback; in-process broadcaster in v1.
- **Jobs:** Database-backed job table with one worker process, for mail
  and digests, reminders, imports, exports, audit verification, form
  activation and closing, virus scanning, PDF assembly, sanitization and
  generation, thumbnails, and retention flags.
- **Mail:** a provider interface. Default: Gmail API over OAuth2 with a
  dedicated free Gmail account. Alternatives: Google Workspace or SMTP.
- **Files:** MinIO (S3-compatible) on the district's servers, private
  bucket, per-file envelope encryption, ClamAV scanning, session-bound
  signed URLs.
- **Scanning on device:** edge detection and image cleanup in a Web Worker;
  PDF assembly on device for camera scans and on the server for uploaded
  images.
- **PWA:** Workbox service worker, IndexedDB for offline data, Web Push via
  VAPID.
- **Deployment:** Docker Compose on the district's servers: API, worker,
  MySQL, MinIO, ClamAV, and a TLS reverse proxy. Backups to a separate
  server.

#### 16.1 Core tables

| Table | Key columns |
|---|---|
| districts | Single row: name, code, default_locale, time_zone, date_format, settings |
| locales, ui_strings, form_translations | Locale codes and translated strings |
| users | id, role, email, staff_id, name, locale, status, mfa_method, totp_secret_enc, totp_last_step, failed_otp_count, locked_until, deleted_at, version |
| recovery_codes (new) | id, user_id, code_hash, used_at |
| otp_codes | user_id, purpose, code_hash, expires_at, used_at |
| sessions | user_id, token_hash, created_at, last_seen_at, ip, user_agent, revoked_at |
| clusters | id, cluster_code, name, cluster_head_id, status, version |
| schools | id, cluster_id, school_code, name, details JSON, custom JSON, status, deleted_at, version |
| school_contacts | id, school_id, teacher_id, start_date, end_date |
| reference_values (new) | id, list (designation, subject, class, qualification), code, status; names in translations |
| custom_field_definitions (new) | id, entity (teacher, school), key, type, required, validation JSON, options JSON, status, sort_order |
| teachers (changed) | id, user_id, school_id, designation_id, experience_years, experience_as_of, custom JSON, status, deleted_at, version |
| teacher_subjects, teacher_classes (new) | teacher_id, reference_value_id |
| teacher_qualifications (new) | teacher_id, reference_value_id, year |
| teacher_transfers | id, teacher_id, from_school_id, to_school_id, moved_at, moved_by |
| supervisors | id, user_id, cluster_id, status, version |
| supervisor_cluster_moves | id, supervisor_id, from_cluster_id, to_cluster_id, moved_at, moved_by |
| supervisor_assignments | id, supervisor_id, school_id, start_date, end_date, status, reason, version |
| ministry_reports (new) | id, report_code (ministry report ID), subject_type |
| ministry_report_versions (new) | id, ministry_report_id, version_code (ministry version ID), title_key, ministry_published_on, source_file_id, status; unique (ministry_report_id, version_code) |
| form_definitions | id, code, subject_type, status |
| form_versions (changed) | id, form_definition_id, ministry_report_version_id, version, schema JSON, status, start_date, end_date, built_by, reviewed_by, published_by, published_at, closed_at, close_reason, version_lock |
| form_review_comments (new) | id, form_version_id, author_id, comment, created_at |
| scoring_rule_sets (new) | id, form_version_id, version, rules JSON, effective_at, created_by |
| evaluations | id, form_version_id, subject_type, school_id, teacher_id, supervisor_id, status, visit_date, submitted_at, amended_at, score JSON, scoring_rule_set_id, version |
| evaluation_sections | id, evaluation_id, section_key, respondent, respondent_user_id, status, answers JSON, due_at, submitted_at, version |
| evaluation_amendments | id, evaluation_id, reason, prior_answers JSON, created_by, created_at |
| stored_files | id, storage_key, mime_type, size, sha256, page_count, scan_status, key_ref, created_by, created_at |
| attachments | id, owner_type, owner_id, stored_file_id, uploaded_by |
| documents (changed) | id, owner_supervisor_id, cluster_id, school_id, teacher_id, evaluation_id, ministry_report_version_id, title, report_date, notes, status, submitted_at, acknowledged_at, acknowledged_by, returned_at, return_comment, current_version_id, deleted_at, archived_at, retention_until, version |
| document_versions | id, document_id, version_no, stored_file_id, reason, client_key, device_time, created_at; unique (document_id, client_key) |
| document_forwards (new) | id, document_id, cluster_id, forwarded_by, note, forwarded_at, revoked_at; access follows the cluster's current Cluster Head |
| notifications | id, user_id, type, payload JSON, read_at, created_at |
| notification_preferences | user_id, type, channel, enabled |
| mail_queue | id, template, recipient, priority, budget_class, status, scheduled_for, provider_message_id, attempts, error, created_at |
| mail_daily_usage (new) | date, sent_count, reserved_used, limit |
| jobs | id, type, payload JSON, status, attempts, run_after, created_at |
| audit_log | seq, actor_id, actor_role, cluster_id, action, entity_type, entity_id, before JSON, after JSON, ip, user_agent, created_at, prev_hash, hash |

The v0.3 tables `document_shares` and `document_access_grants` are
replaced by the submission columns on `documents` and by
`document_forwards`.

Indexes: `documents (owner_supervisor_id, status, report_date)`,
`documents (status, submitted_at)`, `documents (school_id,
ministry_report_version_id)` for coverage, and `form_versions (status,
start_date, end_date)`.

Offline submissions carry a client-generated idempotency key, so retries
are safe. Sync state lives only on the client, in IndexedDB.

### 17. Key workflows

1. **Login:** password, then an emailed code or an authenticator code,
   then session. Each step is audited.
2. **Assign:** conflict check, insert, audit entry, realtime event, and
   notification, in one transaction.
3. **Reassign:** end supervisor A's assignment and start supervisor B's, in
   one transaction. Open drafts need an explicit choice. Documents stay
   with A.
4. **New ministry report version (new):** the Form Author adds the catalog
   entry, copies the previous form into a draft, updates it, previews it in
   both languages, and sends it for review. A District Admin reviews it and
   either returns it with comments or publishes it with start and end
   dates. It activates on the start date and closes after the end date.
5. **School evaluation:** the supervisor starts a draft on an Active form
   and completes supervisor sections. Teacher sections go to the contact
   teacher. The supervisor submits once all required sections are in or
   waived. A PDF report can be generated at any time after submission.
6. **Teacher section:** the teacher completes and submits. The requester
   can return it. Reminders run from the job table and go out in the daily
   digest.
7. **Offline submit:** queued locally, sent in order with idempotency keys.
   Conflicts are shown to the user.
8. **Scan and submit a report (changed):** the supervisor scans pages with
   the camera or picks files, chooses the ministry report and version,
   school, and date, and saves a draft. The upload is queued if offline.
   The server scans and sanitizes the file. The supervisor submits it to
   the District Admins, who are notified. An admin views it (recorded),
   then acknowledges or returns it, and may forward it to the Cluster Head.
   The supervisor follows every step on their dashboard.
9. **Returned report:** the supervisor sees the comment, uploads a new
   version, and submits it again. The admins see both versions.

### 18. Acceptance criteria

Platform:

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
- The mail queue sends login codes before reminders, even when the queue
  is full.

Second factor:

- A user signs in with Google Authenticator. Reusing the same code within
  its window fails.
- A recovery code works once. A second use fails.
- An admin reset to email codes is audited and emails the user.

Language:

- Switching from English to Arabic on a half-filled form keeps every
  answer and mirrors the layout. The choice persists after sign-out.
- A generated PDF in Arabic renders right to left with correct fonts.
- Dates appear as D/MM/YYYY in both languages.

Forms:

- A Form Author cannot open any school, user, evaluation, or document; the
  API returns 404.
- A form missing Arabic text cannot be sent for review.
- A form published with start 5/11/2026 and end 30/11/2026 cannot be used
  on 4/11/2026, becomes usable on 5/11/2026, and stops accepting new
  evaluations after 30/11/2026, all in district time.
- A published form's content cannot be edited; extending its end date is
  audited.
- Every evaluation, PDF, and export shows the ministry report ID and
  version ID.

Scanned reports:

- Supervisors A and B are both assigned to school X. A uploads a report for
  X. B's lists, search, dashboard counts, and realtime events show nothing
  of it, and B gets 404 when requesting it by ID. The denial is audited.
- After school X is reassigned from A to B, B still cannot see any of A's
  reports.
- A signed download URL issued to an admin fails when used from another
  session, after sign-out, or after 5 minutes.
- Both District Admins see a report as soon as it is submitted. When one
  acknowledges it, the other sees who did.
- A Cluster Head gets 404 for a report until an admin forwards it, and 404
  again after the forward is revoked.
- An admin cannot forward a report to a supervisor or a teacher.
- A teacher gets 404 for every report, including reports about them.
- An acknowledged report cannot be withdrawn or deleted by its owner. A
  correction creates a new version, and both stay visible to the admins.
- A supervisor's deleted draft disappears from their list, stays visible
  to admins as Deleted, and can be restored.
- The supervisor dashboard shows, for each Active ministry report, which
  assigned schools have no submitted report.
- An admin's view of a report appears in the supervisor's access history,
  and the admin's download carries their watermark.
- An upload with a forged extension is rejected. A PDF with embedded
  JavaScript is stored without it. An image's GPS EXIF data is removed. The
  EICAR test file is quarantined and never served.
- A report upload queued offline and retried three times creates exactly
  one document.

Mail:

- With the daily budget used up, a login code is still sent from the
  reserve, and a reminder waits until the next day.
- A bulk import of 212 teachers schedules invitations over two days and
  shows the dates to the admin.

Retention:

- No API endpoint or admin screen permanently removes a record.
- The restore test recovers document files whose checksums match their
  records.

### 19. Test strategy

Each test type runs at the cheapest point that still catches its defects.
Full suites do not run on every check-in.

| Level | When it runs | What it covers |
|---|---|---|
| Unit | On each change, touched modules only | Validators, email code and TOTP logic, conflict rules, form schema validation, publishing windows and time zones, scoring rules, locale formatting, hash computation, document state transitions |
| Permission matrix | On changes to auth, roles, scoping, forms, or documents | Table-driven: every role, including Form Author, against every endpoint, with cross-cluster, cross-school, and same-school second supervisor cases |
| Auth abuse | On changes to auth or mail | Code brute force, TOTP replay, recovery code reuse, lockout, rate limits, expired and reused codes |
| API integration | On merge to main | Real MySQL and MinIO in containers: assign, reassign, conflicts, form draft, review, publish and close, evaluations, amendments, sections, requests, returns, report upload, submit, acknowledge, return, forward, soft delete, restore |
| Form builder | On changes to the builder or renderer | Every question type round-trips from builder to renderer; preview matches the live form in both languages |
| File safety | On changes to the file service | Type sniffing, PDF sanitization, EXIF removal, EICAR quarantine, size and page limits, signed URL binding and expiry |
| Mail budget | On changes to mail | Reserve, digest, invitation spreading, next-day carry-over, provider switch |
| Audit integrity | On merge, and on any change to audited code | Each audited action yields one correct entry; hash chain verifies; a simulated tamper is detected |
| Offline sync | On changes to the sync module | Queue order, idempotent replay, conflict handling, storage eviction warning, resumable upload, sign-out wipe, form closed while offline |
| Migrations | On each migration | Applied to a copy of production-shaped data; counts and constraints verified |
| Security scan | Before each release | Dependency audit and OWASP-based scan of a staging build |
| Penetration test | Before go-live, and after major changes to documents or auth | External test focused on access to other users' objects by ID, signed URL abuse, upload attacks, and second-factor bypass |
| Browser end-to-end | Before each release | Login with each second factor, publish a form, assign and evaluate, teacher request, scan and submit, admin acknowledge and forward, on desktop and two mobile viewports, in English and Arabic |
| Accessibility | Before each release | Automated checks plus a keyboard pass on the five critical journeys |
| Localization | Before each release, and when a form or list is added | Pseudo-locale pass, RTL pass, export and watermark font check |
| Device check | Before each release | Install, offline run, and camera scan on one Android device and one iPhone |
| Restore | Monthly | Latest backup restored to a scratch instance; row counts, audit chain, and sampled file checksums verified |
| Load | Before go-live, and after infrastructure change | Realtime connections, list queries, and concurrent uploads at design scale |

Test data comes from one shared fixture module. Nothing is copied between
tests.

### 20. Delivery phases

The product ships in six phases. Each phase ends in a usable release.
Scope, exit criteria, and dependencies are in
[delivery-plan.md](delivery-plan.md).

| Phase | Name | Release |
|---|---|---|
| 1 | Foundation and district structure | Staging. Admins build the district from imports in English and Arabic. |
| 2 | Forms, supervision, and scanned reports | Pilot 1: one cluster. Admins publish forms; supervisors evaluate online and submit scanned reports to the admins. |
| 3 | Teacher participation | Pilot 1 extended to teachers in the pilot cluster. |
| 4 | Mobile, offline, and realtime | Pilot 2: the whole district. |
| 5 | Scoring, reporting, administration, and go-live | Production go-live. |
| 6 | After v1 | Backlog, ordered by district priority. |

### 21. Open questions

Each question must be answered before the phase shown.

1. **Structure (before Phase 1):** How many clusters, Cluster Heads, and
   schools are there? Which cluster runs Pilot 1?
2. **School fields (before Phase 1):** Confirm the required school fields:
   name, school ID, cluster, address, type, medium of instruction, contact
   details.
3. **Extra teacher fields (before Phase 3):** Name and type of the 8 to 10
   additional teacher fields. These are configuration, so they do not
   block Phase 1.
4. **Reference lists (before Phase 1):** The values, in English and Arabic,
   for designations, subjects, classes, and qualifications.
5. **Cluster Head access (before Phase 2):** Is a report seen by the
   Cluster Head only when an admin forwards it? Or should every report on a
   cluster's schools reach its Cluster Head automatically?
6. **Form building (before Phase 2):** Will only the implementation team
   build forms, or should District Admins also be able to build them?
7. **Arabic digits (before Phase 1):** In Arabic, show Western digits
   (0-9) or Eastern Arabic digits (٠-٩)?
8. **Ministry reports (before Phase 2):** The list of ministry reports for
   launch, with report IDs, version IDs, and source documents.
9. **Scoring formula (before Phase 5):** The formula document, and which
   forms it applies to.
10. **Backups (before Phase 1):** Which server holds backups? Is an
    encrypted off-site copy allowed?
11. **Authenticator for admins (before Phase 1):** Is it acceptable to
    require Google Authenticator for District Admins?
12. **Mail account (before Phase 1):** Will the district create a dedicated
    Gmail account for system mail? A dedicated account is recommended, so
    personal mail never shares its quota.
13. **Server and network (before Phase 1):** Who operates the servers, and
    can they be reached from the internet with a public domain name and
    certificate?
