# Operations runbooks

For the district's IT staff and District Admins. Each runbook says when to use it, what to do,
and how to check it worked. Commands run on the server, in the deployment directory
(`/opt/sces` in these examples), unless they say otherwise. Installation, mail setup and
upgrades are in the [deployment guide](deployment.md).

Targets these runbooks keep (requirements section 15): data lost at most 24 hours back
(RPO), service back within 8 hours (RTO), 99.5% availability during school hours.

Contents:

1. [Daily: check the backup ran](#1-daily-check-the-backup-ran)
2. [Monthly: restore test](#2-monthly-restore-test)
3. [The server is lost: full restore](#3-the-server-is-lost-full-restore)
4. [An admin is locked out: break-glass reset](#4-an-admin-is-locked-out-break-glass-reset)
5. [A user lost their authenticator](#5-a-user-lost-their-authenticator)
6. [A file was quarantined](#6-a-file-was-quarantined)
7. [Mail budget alert, or mail not arriving](#7-mail-budget-alert-or-mail-not-arriving)
8. [Moving to a paid mail plan](#8-moving-to-a-paid-mail-plan)
9. [The audit chain check failed](#9-the-audit-chain-check-failed)
10. [Security incident](#10-security-incident)
11. [Before each release: security scan and load test](#11-before-each-release-security-scan-and-load-test)

---

## 1. Daily: check the backup ran

**When:** every working morning, or from monitoring.

1. Check last night's log:

   ```bash
   tail -n 3 /var/log/sces-backup.log
   ```

   The last line reads `backup written: ...sql.gz.enc and ...files.tar.enc`.
2. Check both archives and their checksums exist and are recent:

   ```bash
   ls -lt "$SCES_BACKUP_DIR" | head -n 5
   ```

3. Check the copy reached the separate server or disk (Q10: the off-site copy, if the district
   keeps one).

**If it failed:** run `deploy/backup.sh` by hand and read its error. The usual causes are a full
backup disk (backups older than 30 days are removed automatically, so a full disk means it is too
small) and a stopped `db` or `api` container (`docker compose ps`).

## 2. Monthly: restore test

**When:** once a month (section 19), and after any change to the backup scripts. Record the
date, the backup used, the times and the results.

On a **scratch server** with the same installation, never on production:

1. Copy the latest database and file archives, their `.sha256` files, the passphrase file and
   a copy of production's `.env` (it holds the encryption keys; without it the files cannot be
   read).
2. Start an empty stack and note the time:

   ```bash
   docker compose up -d
   ```

3. Restore:

   ```bash
   deploy/restore.sh /srv/sces-backups/sces-20261105T011500Z.sql.gz.enc
   ```

   ```bash
   docker compose restart api worker
   ```

4. Check the audit chain and every file against its recorded checksum:

   ```bash
   docker compose exec api python -m app.cli verify-audit
   ```

   ```bash
   docker compose exec api python -m app.cli verify-files
   ```

   Both must report no failures. `verify-files` without `--sample` checks every file; on a
   large vault use `--sample 500` monthly and the full check quarterly.
5. Sign in as an admin, open a recent scanned report and a recent evaluation PDF.
6. Compare row counts with production for the same night (users, schools, evaluations,
   documents, stored files, audit entries):

   ```bash
   docker compose exec db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" sces -e "select count(*) from documents; select count(*) from stored_files; select count(*) from audit_log"'
   ```

**Measured on 30/10/2026** (Compose stack, test data): backup 2 s, restore 5 s, from an empty
server to service 40 s, all counts and every file checksum matching. A database at design scale
(200,000 reports, 50,000 evaluations, 10,000 teachers) restored in 15 s. File volume time is
mostly copying: about 1.5 hours per terabyte at 200 MB/s.

## 3. The server is lost: full restore

**When:** the server or its disks cannot be recovered. Target: service back within 8 hours.

1. Tell users through the district's usual channel that the system is down and work done
   offline on phones is kept on the phones and will be sent later.
2. Install the system on the replacement server (deployment guide, sections 1 and 2), using a
   copy of the old `.env`. Without the old `SCES_ENCRYPTION_KEY` the stored files cannot be
   decrypted: the key and the passphrase must come from the backup copy of `.env`.
3. Point the DNS name at the new server, so Caddy can obtain its certificate.
4. Restore the latest backup and check it, as in runbook 2, steps 3 and 4.
5. Sign in as an admin and check the dashboard: the audit check, mail, storage.
6. Tell users the system is back. Phones send their waiting work automatically; anything
   created after the last backup and not on a phone must be entered again.
7. Record the incident (runbook 10, step 6), including the times.

## 4. An admin is locked out: break-glass reset

**When:** a District Admin has lost their authenticator and recovery codes, and no other admin
can reset them in the app (Staff page, "Reset sign-in method").

1. Confirm who is asking, in person or by a call back to a number on file. This reset gives
   full access to whoever holds the account.
2. On the server:

   ```bash
   docker compose exec api python -m app.cli break-glass-reset --email admin1@example.org
   ```

   This writes a critical audit entry and emails every other admin (FR-A9).
3. The admin signs in with a code sent by email, then sets up a new authenticator and saves
   new recovery codes. Admins cannot stay on email codes.
4. The other admins check the audit log (Audit log page, action `break_glass.mfa_reset`) and confirm the
   reset was expected.

## 5. A user lost their authenticator

**When:** a user cannot sign in because their phone or authenticator app is gone.

1. If they still have a recovery code, they use it on the sign-in page ("Use a recovery code instead")
   and set up a new authenticator. Each code works once.
2. Otherwise an admin resets them: "Reset sign-in method" next to the person on the Staff,
   Teachers or Supervisors page. The person gets email codes until they set up an authenticator again;
   roles that must use one (Settings → Sign-in and security) are asked to at once. The reset is
   audited and the person is emailed.
3. For an admin who is the only one who could do the reset, use runbook 4.

## 6. A file was quarantined

**When:** the virus scanner flagged an upload. The uploader and every admin get an email, and
the admin dashboard shows the count.

1. Find it: Audit log → action `file.quarantined`. The entry names the file and the signature
   found; the uploader was emailed.
2. A quarantined file is never served to anyone, and the system cannot release it: this is by
   design. Ask the uploader to scan their device and upload a clean copy (for a scanned report,
   "Upload new version").
3. If it is a known false positive (rare; for example a new ClamAV signature), keep the
   signature name with the incident record and ask the uploader to save the document again as
   a new PDF before uploading.
4. If several files from one device are flagged, treat it as runbook 10.

## 7. Mail budget alert, or mail not arriving

**When:** admins get the "80% of today's mail limit used" alert, or users say codes do not
arrive.

1. Check the dashboard (System: "Mail sent today: X of Y. Waiting in the queue: Z.").
2. Sign-in codes always go first and have a reserve (Settings → Mail: "Share kept for sign-in
   codes"). When the general budget is used up, notices wait in the queue until the next day;
   nothing is lost.
3. If even codes do not arrive:
   - Check the worker is running: `docker compose ps worker` and `docker compose logs --tail 50 worker`.
   - Check the provider: for Gmail API, a revoked or expired refresh token shows as
     `invalid_grant` in the worker log (deployment guide, section 4, step 2); for SMTP, a
     rejected login.
   - Check the daily limit set in Settings is not above the provider's real limit.
4. If the budget runs out most days, move to a paid plan (runbook 8) or raise the limit to what
   the plan allows.

## 8. Moving to a paid mail plan

**When:** the free Gmail limit (about 500 a day) is not enough, for example during teacher
invitations or the first weeks of a new term (FR-N9).

1. Choose the plan: Google Workspace (about 2,000 a day per account) or an SMTP relay.
2. Change `.env` only:
   - Workspace through the Gmail API: new `SCES_GMAIL_*` values for the Workspace account.
   - SMTP: `SCES_MAIL_PROVIDER=smtp` and the `SCES_SMTP_*` values.
3. Apply:

   ```bash
   docker compose up -d
   ```

4. In Settings → Mail, raise "Daily mail limit" to the new plan's limit, and set the sender name.
5. Send yourself a test: request a sign-in code for a test account and check it arrives.

## 9. The audit chain check failed

**When:** every admin gets the critical "audit log check failed" email, and the dashboard shows
it.

1. Do not change anything in the database. Take a backup now (`deploy/backup.sh`) to keep the
   evidence.
2. Run the check by hand to see where it breaks:

   ```bash
   docker compose exec api python -m app.cli verify-audit
   ```

3. The entry it names was changed, removed, or the log was cut short after that point. The
   application's database user cannot do this (FR-L3), so someone used other database access.
4. Compare with the last backup whose check passed: restore it on a scratch server (runbook 2)
   and compare the entries around the break.
5. Handle it as a security incident (runbook 10).

## 10. Security incident

**When:** suspected unauthorized access, a leaked password or device, a broken audit chain,
or repeated quarantines.

1. **Contain.**
   - A person's account: deactivate it (Staff, Teachers or Supervisors page). This signs them
     out everywhere at once.
   - A lost phone: the person signs in elsewhere and removes the phone under My account →
     Signed-in devices, or an admin deactivates and reactivates the account.
   - Everyone, if a server secret may have leaked: sign every session out:

     ```bash
     docker compose exec db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" sces -e "update user_sessions set revoked_at = utc_timestamp(6), revoke_reason = \"incident\" where revoked_at is null"'
     ```

2. **Keep the evidence.** Take a backup. Export the audit log for the period (Audit log page →
   filters → Export to Excel); the export is itself audited.
3. **Find out what happened.** In the audit log, filter by the account (actor ID), by
   `permission.denied`, `login.failed`, `support.`, `file.downloaded` and `documents.exported`.
   Each entry has the time, the address and the device.
4. **Fix the cause:** reset passwords and second factors, update the server, rotate the mail
   provider's credentials, replace the TLS certificate if the server was entered.
5. **Tell** the people whose data was involved, as the district's policy and the law require.
   An admin can export everything held about a person (Support page → "Export their data").
6. **Record** what happened, when it was found, what was done and what changes to prevent it,
   with the audit export, in the district's incident register.

The `SCES_ENCRYPTION_KEY` protects every stored file. It cannot be changed in place: if it may
have leaked, treat the files as exposed, and plan a re-encryption with the supplier.

## 11. Before each release: security scan and load test

**When:** before each release (section 19), on a staging copy, never on production.

1. Security scan: OWASP ZAP against the staging stack, a baseline of the web app and an active
   scan of the API signed in as an admin. The scripts used for go-live are in `security/`; see
   `security/README.md`. No high or medium finding may stay open.
2. Dependency audits:

   ```bash
   cd backend && pip-audit --local
   ```

   ```bash
   cd frontend && npm audit --omit=dev
   ```

3. Load test at design scale: `loadtest/` (see its README); compare with the last results in
   the delivery plan.
4. Accessibility and language checks: `e2e/a11y.cjs` and the web app's unit tests (which
   include the check that no screen text is left untranslated).
5. The browser tests (`e2e/phase2.cjs` to `e2e/phase4.cjs`) against the staging stack.
