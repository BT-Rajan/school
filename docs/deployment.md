# Deployment guide

How to install the School Cluster Evaluation System on the district's own
server. One installation serves one district (requirements section 2).

There are two ways: Docker Compose (sections 1 to 9 below), or `install.sh` on a server that
already has MariaDB and pm2 (section 0).

## 0. Install with install.sh (MariaDB and pm2, no Docker)

Needs: Ubuntu or Debian; MariaDB 10.6 or later (or MySQL 8) with an empty database and a
user that has all rights on it; Python 3.12 or later; Node.js 20.19 or later. Run as root (with
`sudo`), so the script can install what is missing (pm2, ClamAV) and set pm2 to start on boot.

From a checkout of this repository:

```bash
sudo DB_PASSWORD='the database password' ./install.sh
```

The defaults are in the first lines of the script: `/apps/school`, port 8388, database
`school` on `127.0.0.1:3306`, user `app_user`. Each can be overridden the same way as
`DB_PASSWORD`, for example `DB_HOST=10.0.0.5`. Useful on the first run:

- `ADMIN_EMAIL=you@example.org ADMIN_NAME='Your Name'` invites the first District Admin and
  prints the link.
- `PUBLIC_URL=https://sces.example.org` when an HTTPS reverse proxy is in front of port 8388.
  Without HTTPS, phones cannot install the app, use the camera scanner, work offline or get
  push notices.
- `MAIL_PROVIDER=smtp SMTP_HOST=... SMTP_USERNAME=... SMTP_PASSWORD=...`, or the `GMAIL_*`
  values (section 4). Until mail is set, nobody but the first admin can sign in.

What it does:

1. Copies the code to `/apps/school`.
2. Writes `/apps/school/.env`, readable by its owner only. On the first run it generates the
   keys; keep a copy of this file with the backups.
3. Installs the Python packages and builds the web app.
4. Converts the database to utf8mb4 if needed, and migrates it.
5. Creates the district record.
6. Installs ClamAV, listening on 127.0.0.1:3310.
7. Starts `sces-api` (the API and the web app on port 8388) and `sces-worker` under pm2, and
   saves them for reboot.

To upgrade, pull the new code and run `sudo ./install.sh` again. The password, keys and files
are kept.

Differences from the Compose install:

- The database user has all rights on its database, so the audit log is not insert-only at the
  database level (FR-L3). The daily hash-chain check still detects any change. To restore
  insert-only, have a database administrator apply `python -m app.cli grants-sql` to a
  separate application user.
- `deploy/backup.sh` uses Docker. Back up with `mariadb-dump` of the database and a copy of
  `/apps/school/data/files` and `/apps/school/.env`, taken together (section 5 explains why).

## 1. Server requirements

- A Linux server with Docker Engine and the Docker Compose plugin.
- 4 CPU cores, 8 GB RAM and 100 GB disk are enough for the current district
  (2 admins, 30 supervisors, about 180 teachers). Scanned reports in Phase 2
  will need more disk; plan for growth.
- A public domain name, for example `sces.example.org`, pointing at the server.
- Ports 80 and 443 open to the internet. Phones in the field must reach the
  server over HTTPS (Q13). The web container obtains and renews a trusted
  certificate automatically.
- A second machine or disk for backups (Q10).

## 2. Install

```bash
git clone https://github.com/BT-Rajan/school.git /opt/sces
```

```bash
cd /opt/sces && cp .env.example .env && chmod 600 .env
```

Generate the two application keys and paste them into `.env` as
`SCES_SECRET_KEY` and `SCES_ENCRYPTION_KEY`:

```bash
openssl rand -base64 48
```

```bash
openssl rand -base64 32 | tr '+/' '-_' | tr -d '='
```

Fill in the rest of `.env`: the domain, two long random database passwords,
and the mail settings (section 4).

Keep a copy of `.env` somewhere safe. `SCES_ENCRYPTION_KEY` encrypts
authenticator secrets; without it, every authenticator user must be reset.

Start the stack. The `migrate` service runs database migrations and creates the
restricted database user before the API starts:

```bash
docker compose up -d --build
```

## 3. First-time setup

Create the district record:

```bash
docker compose exec api python -m app.cli bootstrap --code KW-HAW --name-en "Hawalli Education District" --name-ar "منطقة حولي التعليمية" --time-zone Asia/Kuwait
```

Invite the two District Admins (at least two are required, FR-AD5). Each
command prints the invitation link as well as emailing it:

```bash
docker compose exec api python -m app.cli create-admin --email admin1@example.org --name "First Admin" --staff-id A-001
```

```bash
docker compose exec api python -m app.cli create-admin --email admin2@example.org --name "Second Admin" --staff-id A-002
```

Admins must set up Google Authenticator when they accept the invitation. After
signing in, an admin:

1. Fills the reference lists (designations, subjects, classes, qualifications)
   in English and Arabic.
2. Adds any extra teacher or school fields under Custom fields.
3. Creates the Cluster Heads, then the clusters.
4. Imports schools, teachers and supervisors from the templates under Import and
   export. Invitations are spread over several days to stay within the mail limit.

Form Authors (implementation team) are invited with:

```bash
docker compose exec api python -m app.cli create-form-author --email author@example.org --name "Form Author"
```

## 4. Mail

The system sends sign-in codes, invitations and notices. With a free Gmail
account the daily limit is about 500 recipients (set by Google). The system
keeps 40% of the daily limit for sign-in codes and queues the rest (FR-N8).
Admins can change these numbers under Settings.

Use a dedicated Gmail account for the system (Q12), not a personal one.

### Option A: Gmail API (default)

1. In Google Cloud Console, create a project and enable the Gmail API.
2. Configure the OAuth consent screen as External and add the
   `https://www.googleapis.com/auth/gmail.send` scope. Set the publishing status
   to **In production**. In Testing status, Google expires refresh tokens after
   7 days and mail stops.
3. Create an OAuth client ID of type Web application, with
   `https://developers.google.com/oauthplayground` as a redirect URI.
4. In the OAuth 2.0 Playground, use your own client ID and secret, authorize the
   `gmail.send` scope while signed in as the system's Gmail account, and
   exchange the code for a refresh token.
5. Put the client ID, client secret, refresh token and the account address in
   `.env` (`SCES_GMAIL_*`, `SCES_MAIL_SENDER`), then run `docker compose up -d`.

### Option B: SMTP

This works with Gmail (an app password, which needs 2-Step Verification on the
account), with Google Workspace, or with any relay. Set `SCES_MAIL_PROVIDER=smtp`
and the `SCES_SMTP_*` values. Use `smtp.gmail.com` on port 587 for Gmail.

Moving to a paid plan later only changes `.env` (FR-N9).

## 5. Backups and restore

`deploy/backup.sh` writes two encrypted archives with checksums: a compressed
database dump and the file volume. It deletes backups older than 30 days. Create the passphrase file
once and store a copy offline:

```bash
openssl rand -base64 48 > /root/.sces-backup-passphrase && chmod 600 /root/.sces-backup-passphrase
```

Run the backup daily from cron (RPO 24 hours):

```bash
echo '15 1 * * * root cd /opt/sces && deploy/backup.sh >> /var/log/sces-backup.log 2>&1' > /etc/cron.d/sces-backup
```

Each month, restore the latest backup on a scratch server and check the audit
chain and the stored files (section 19, Restore). `restore.sh` restores the
matching file archive too:

```bash
deploy/restore.sh /srv/sces-backups/sces-20261105T011500Z.sql.gz.enc
```

```bash
docker compose exec api python -m app.cli verify-audit
```

```bash
docker compose exec api python -m app.cli verify-files --sample 50
```

`verify-files` decrypts each sampled file and compares it with its recorded
checksum. Without `--sample` it checks every file.

## 5a. Push notifications (optional)

Users can allow notices on their phone or computer from the Notifications page.
To turn this on, generate a key pair once and put it in `.env`:

```bash
docker compose run --rm api python -m app.cli generate-keys
```

Copy `SCES_VAPID_PUBLIC_KEY` and `SCES_VAPID_PRIVATE_KEY` from the output (ignore
the other keys it prints), set `SCES_VAPID_SUBJECT` to the district's contact
address, and restart. The server sends only to the browsers' own push services
(Google, Mozilla, Microsoft, Apple), so outbound HTTPS to them must be allowed.
Changing the keys means every device has to turn push on again.

## 6. Files and virus scanning

Uploaded files are stored in the `files-data` volume. Each file is encrypted
with its own key before it is written, so the volume never holds readable
content. Files are scanned by the `clamav` service before anyone can open
them; a file that fails is kept in quarantine and the uploader and admins are
emailed.

ClamAV downloads new virus signatures several times a day, so the server needs
outbound internet access to `database.clamav.net`. If the scanner is down,
uploads wait and are scanned when it returns; nothing is served unscanned.

Upload limits (size, pages, uploads per hour, storage per person) are under
Settings. The upload size can be set up to 59 MB. Above that, the web server
and the API both refuse the request before reading it (60 MB for uploads, 2 MB
for everything else), so a single request cannot fill the disk. To allow
larger files, raise `max_size` in `frontend/Caddyfile` and set
`SCES_MAX_UPLOAD_REQUEST_MB` for the `api` service to the same value.

## 7. Emergency access

If a District Admin loses their phone and recovery codes while no other admin
can reset them, run the break-glass reset on the server (FR-A9). It writes a
critical audit entry and emails all other admins:

```bash
docker compose exec api python -m app.cli break-glass-reset --email admin1@example.org
```

## 8. Audit log integrity

The worker verifies the audit hash chain every night at 02:00 district time
and alerts every admin by email if it is broken. To check now:

```bash
docker compose exec api python -m app.cli verify-audit
```

The application's database user can only read and add audit rows, never
change or delete them (FR-L3). `provision-database` reapplies these grants on
every deploy.

## 9. Upgrades

```bash
cd /opt/sces && git pull && docker compose up -d --build
```

Migrations run automatically through the `migrate` service before the API
restarts. Take a backup first.
