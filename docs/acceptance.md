# Acceptance criteria (requirements section 18)

Each criterion and what shows it passes on the release build. Backend tests run against MySQL 8 on
every push (CI); browser tests run against the production build and the full Compose stack (Caddy
with HTTPS, ClamAV) before each release. Paths are relative to the repository.

Status: **all criteria pass**, except the two marked *district*, which need the district's real
devices or data.

## Platform

| Criterion | Evidence |
|---|---|
| An unassigned supervisor gets 403 on a school's evaluations, and the denial is audited. | `backend/tests/test_evaluations.py::test_only_assigned_schools_and_active_forms` |
| Two Cluster Heads reassigning the same school at once: one succeeds, the other gets 409 with the current state. | `backend/tests/test_assignments.py::test_concurrent_reassign_one_wins` |
| After a reassignment, history shows both supervisors with correct dates. | `backend/tests/test_assignments.py::test_reassign_keeps_history` |
| A locked account cannot log in until unlocked, even with the correct password. | `backend/tests/test_auth.py::test_lockout_after_five_bad_codes`, `::test_admin_unlocks_a_locked_account` |
| A submitted evaluation cannot be edited. An amendment keeps prior answers and writes an audit entry. | `backend/tests/test_evaluations.py::test_full_lifecycle` |
| An audit row cannot be edited or deleted through the application. A manual database tamper is detected by the daily hash check. | `backend/tests/test_audit.py::test_app_database_user_cannot_change_audit_rows`, `::test_tampered_content_is_detected`, `::test_deleted_entry_is_detected`, `::test_truncated_tail_is_detected`; `backend/tests/test_worker.py::test_grants_sql_keeps_audit_insert_only` |
| An offline draft survives an app restart and syncs once online, with no duplicate. | `e2e/phase4.cjs` (Chromium, preview build and Compose stack); real Android and iPhone: *district* |
| A teacher gets 404 for another teacher's request, even when calling by ID. | `backend/tests/test_requests.py::test_school_evaluation_goes_to_the_contact_teacher`, `e2e/phase3.cjs` |
| Break-glass 2FA reset requires server access, writes a critical audit entry, and notifies all admins. | `backend/tests/test_auth.py::test_break_glass_reset` |
| The mail queue sends login codes before reminders, even when the queue is full. | `backend/tests/test_mail.py::test_security_mail_goes_first`, `::test_reserve_keeps_room_for_login_codes` |

## Second factor

| Criterion | Evidence |
|---|---|
| A user signs in with Google Authenticator. Reusing the same code within its window fails. | `backend/tests/test_auth.py::test_authenticator_login_and_replay_rejected` |
| A recovery code works once. A second use fails. | `backend/tests/test_auth.py::test_admin_invitation_requires_authenticator_and_issues_recovery_codes` |
| An admin reset to email codes is audited and emails the user. | `backend/tests/test_auth.py::test_admin_resets_lost_authenticator` |

## Language

| Criterion | Evidence |
|---|---|
| Switching from English to Arabic on a half-filled form keeps every answer and mirrors the layout. The choice persists after sign-out. | `frontend/src/language.test.tsx`, `e2e/phase2.cjs` |
| A generated PDF in Arabic renders right to left with correct fonts. | `backend/tests/test_evaluations.py::test_pdf_report[ar]`, `backend/tests/test_reporting.py::test_exports_are_audited_in_both_languages` (embedded font checked; pages inspected by eye) |
| Dates appear as D/MM/YYYY in both languages. | `frontend/src/format.test.ts`; exports: `backend/app/reporting/render.py` |

## Forms

| Criterion | Evidence |
|---|---|
| A Form Author cannot open any school, user, evaluation, or document; the API returns 404. | `backend/tests/test_structure.py::test_form_author_sees_no_district_data`, `::test_permission_matrix` |
| A form missing Arabic text cannot be sent for review. | `backend/tests/test_forms.py::test_missing_arabic_blocks_review` |
| A form published 5/11/2026 to 30/11/2026 cannot be used on 4/11, becomes usable on 5/11, and stops accepting new evaluations after 30/11, in district time. | `backend/tests/test_forms.py::test_review_return_and_publish_window` |
| A published form's content cannot be edited; extending its end date is audited. | `backend/tests/test_forms.py::test_published_content_is_locked_and_window_changes_audited` |
| Every evaluation, PDF, and export shows the ministry report ID and version ID. | `backend/tests/test_evaluations.py::test_pdf_report`, `backend/tests/test_reporting.py::test_raw_answers_by_form` |

## Scanned reports

| Criterion | Evidence |
|---|---|
| Supervisors A and B both assigned to school X: B's lists, search, dashboard counts and realtime events show nothing of A's report, and B gets 404 by ID, audited. | `backend/tests/test_documents.py::test_another_supervisor_on_the_same_school_sees_nothing`, `backend/tests/test_reporting.py::test_search_within_scope`, `::test_scanned_reports_follow_document_isolation`, `backend/tests/test_realtime.py::test_events_reach_only_those_who_may_see_them`, `::test_the_bulk_audience_matches_the_rule_for_everyone`, `e2e/phase4.cjs`; at design scale, 400 other supervisors' connections received none of 1,000 deliveries (`loadtest/`) |
| After school X is reassigned from A to B, B still cannot see any of A's reports. | `backend/tests/test_documents.py::test_reassignment_never_moves_documents` |
| A signed download URL issued to an admin fails from another session, after sign-out, or after 5 minutes. | `backend/tests/test_files.py::test_links_are_bound_to_session_and_expire`, `backend/tests/test_documents.py::test_admin_link_does_not_work_in_another_session` |
| Both District Admins see a report as soon as it is submitted; when one acknowledges it, the other sees who did. | `backend/tests/test_documents.py::test_admins_review_and_see_each_others_actions` |
| A Cluster Head gets 404 for a report until an admin forwards it, and 404 again after the forward is revoked. | `backend/tests/test_documents.py::test_cluster_head_sees_only_forwarded_reports` |
| An admin cannot forward a report to a supervisor or a teacher. | `backend/tests/test_documents.py::test_only_admins_forward_and_only_to_the_cluster_head` |
| A teacher gets 404 for every report, including reports about them. | `backend/tests/test_documents.py::test_teachers_and_form_authors_see_nothing` |
| An acknowledged report cannot be withdrawn or deleted by its owner; a correction creates a new version, both visible to admins. | `backend/tests/test_documents.py::test_acknowledged_reports_are_locked_records` |
| A supervisor's deleted draft disappears from their list, stays visible to admins as Deleted, and can be restored. | `backend/tests/test_documents.py::test_soft_delete_and_restore` |
| The supervisor dashboard shows, for each Active ministry report, which assigned schools have no submitted report. | `backend/tests/test_documents.py::test_supervisor_dashboard` |
| An admin's view of a report appears in the supervisor's access history, and the admin's download carries their watermark. | `backend/tests/test_documents.py::test_watermark_for_everyone_but_the_owner` |
| A forged extension is rejected; a PDF with embedded JavaScript is stored without it; GPS EXIF is removed; the EICAR file is quarantined and never served. | `backend/tests/test_files.py::test_forged_extension_and_unknown_types_rejected`, `::test_pdf_active_content_is_removed`, `::test_image_exif_and_gps_removed`, `::test_infected_file_is_quarantined_and_never_served`, `::test_real_clamd_detects_eicar` (Compose stack) |
| A report upload queued offline and retried three times creates exactly one document. | `backend/tests/test_documents.py::test_retried_upload_creates_one_document`, `backend/tests/test_offline.py::test_a_dropped_upload_resumes_and_a_replay_never_duplicates`, `e2e/phase4.cjs` |

## Mail

| Criterion | Evidence |
|---|---|
| With the daily budget used up, a login code is still sent from the reserve, and a reminder waits until the next day. | `backend/tests/test_mail.py::test_reserve_keeps_room_for_login_codes` |
| A bulk import of 212 teachers schedules invitations over two days and shows the dates to the admin. | `backend/tests/test_mail.py::test_invitations_spread_over_days`, `backend/tests/test_requests.py::test_teachers_are_invited_in_bulk_within_the_daily_cap` |

## Retention

| Criterion | Evidence |
|---|---|
| No API endpoint or admin screen permanently removes a record. | `backend/tests/test_retention.py::test_no_endpoint_removes_a_record_permanently` (the only DELETE route marks a sign-in session revoked) |
| The restore test recovers document files whose checksums match their records. | Restore drill on the Compose stack (`deploy/backup.sh`, `deploy/restore.sh`, `verify-files --sample 0`); see delivery plan, Phase 5 |

## Exit criteria of Phase 5 not covered above

| Criterion | Evidence |
|---|---|
| Scores match the district's formula on worked examples it supplies. | A rule set cannot be activated until every worked example matches (`backend/tests/test_scoring.py`). The examples: *district* (Q9). |
| Penetration test has no open critical or high findings. | Internal OWASP ZAP scans (baseline and authenticated API scan) found none; see `docs/security-review-phase5.md`. The external test: *district*. |
| Load test meets section 15 targets. | `loadtest/` at design scale; see delivery plan, Phase 5. Every list under 300 ms except report search by text (95th percentile 313 ms); realtime 75 ms. |
| Restore test recovers data within the RTO. | Restore drill; see delivery plan, Phase 5 |
| Reports export correctly in English and Arabic. | `backend/tests/test_reporting.py::test_exports_are_audited_in_both_languages` |
