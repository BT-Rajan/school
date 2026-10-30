#!/usr/bin/env bash
# One-step install or upgrade of the School Cluster Evaluation System on a server with
# MariaDB (10.6 or later) and pm2, without Docker.
#
#   sudo DB_PASSWORD='...' ./install.sh
#
# Run it from a checkout of this repository. It copies the code to APP_DIR, builds the web
# app, installs the API's Python packages, migrates the database, sets up the virus scanner,
# and starts two pm2 processes: sces-api (the API and the web app, on PORT) and sces-worker
# (mail, reminders, scans, the daily audit check). Running it again upgrades in place and
# keeps .env, its keys and the stored files.
#
# Settings below can be overridden from the environment. The database password is never
# kept in this file: give it as DB_PASSWORD, or it is read from an earlier install's .env,
# or asked for once.
set -euo pipefail

APP_DIR="${APP_DIR:-/apps/school}"
PORT="${PORT:-8388}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_NAME="${DB_NAME:-school}"
DB_USER="${DB_USER:-app_user}"
# How people reach the server. Default: this server's address on PORT, over plain HTTP.
# Behind an HTTPS reverse proxy, set it to the proxy's address, e.g. https://sces.example.org
PUBLIC_URL="${PUBLIC_URL:-}"
# First install only: the district record, and optionally the first District Admin.
DISTRICT_CODE="${DISTRICT_CODE:-SCHOOL}"
DISTRICT_NAME_EN="${DISTRICT_NAME_EN:-School District}"
DISTRICT_NAME_AR="${DISTRICT_NAME_AR:-المنطقة التعليمية}"
TIME_ZONE="${TIME_ZONE:-Asia/Kuwait}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
ADMIN_NAME="${ADMIN_NAME:-District Admin}"
ADMIN_STAFF_ID="${ADMIN_STAFF_ID:-ADMIN1}"
# clamd (required in production). "none" only where ClamAV cannot be installed: uploads are
# then not virus checked, and the install runs as "staging".
VIRUS_SCANNER="${VIRUS_SCANNER:-clamd}"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"
RUN_USER="${SUDO_USER:-$(id -un)}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
as_user() { if [ "$(id -u)" = 0 ] && [ "$RUN_USER" != root ]; then sudo -u "$RUN_USER" -H "$@"; else "$@"; fi; }
have() { command -v "$1" >/dev/null 2>&1; }
can_apt() { [ "$(id -u)" = 0 ] && have apt-get; }
apt_install() { DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@" >/dev/null; }

# Prerequisites ----------------------------------------------------------------------------

say "Checking prerequisites"
APT_UPDATED=
apt_update() { [ -n "$APT_UPDATED" ] || { apt-get update -q >/dev/null; APT_UPDATED=1; }; }

find_python() {
  for p in python3.13 python3.12 python3; do
    if have "$p" && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
      echo "$p"; return
    fi
  done
}
PYTHON="$(find_python)"
if [ -z "$PYTHON" ] && can_apt; then
  apt_update; apt_install python3.12 python3.12-venv || true
  PYTHON="$(find_python)"
fi
[ -n "$PYTHON" ] || fail "Python 3.12 or later is needed (python3.12 and python3.12-venv)."
if ! "$PYTHON" -c 'import venv, ensurepip' 2>/dev/null; then
  can_apt && { apt_update; apt_install "$(basename "$PYTHON")-venv" || apt_install python3-venv; }
  "$PYTHON" -c 'import venv, ensurepip' 2>/dev/null || fail "The venv module is missing: install $(basename "$PYTHON")-venv."
fi
echo "python: $($PYTHON --version)"

node_ok() { have node && node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>20||(a===20&&b>=19)?0:1)'; }
if ! node_ok && can_apt; then
  apt_update; apt_install nodejs npm || true
fi
node_ok || fail "Node.js 20.19 or later is needed to build the web app (found: $(node --version 2>/dev/null || echo none))."
echo "node: $(node --version)"

if ! have pm2; then
  say "Installing pm2"
  npm install -g pm2 >/dev/null || fail "Could not install pm2 (npm install -g pm2)."
fi
PM2="$(command -v pm2)"
echo "pm2: $($PM2 --version 2>/dev/null | tail -1)"
have rsync || { can_apt && { apt_update; apt_install rsync; }; } || true
have rsync || fail "rsync is needed."
have curl || { can_apt && { apt_update; apt_install curl; }; } || true

# Code -------------------------------------------------------------------------------------

say "Copying the application to $APP_DIR"
mkdir -p "$APP_DIR" "$APP_DIR/data/files" "$APP_DIR/logs"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  # .env, the stored files and the built environments stay; everything else follows the checkout.
  rsync -a --delete \
    --exclude '/.git' --exclude '/.env' --exclude '/data' --exclude '/logs' \
    --exclude '/backend/.venv' --exclude 'node_modules' --exclude '/frontend/dist' \
    --exclude '__pycache__' --exclude '*.egg-info' \
    "$SRC_DIR/" "$APP_DIR/"
fi
[ "$(id -u)" = 0 ] && chown -R "$RUN_USER": "$APP_DIR"

# Settings ---------------------------------------------------------------------------------

env_value() { if [ -f "$ENV_FILE" ]; then sed -n "s/^$1='\(.*\)'$/\1/p" "$ENV_FILE" | tail -1; fi; }

if [ -z "${DB_PASSWORD:-}" ] && [ -f "$ENV_FILE" ]; then
  DB_PASSWORD="$("$PYTHON" -c 'import sys, urllib.parse; print(urllib.parse.unquote(sys.argv[1]))' "$(env_value SCES_DB_PASSWORD_ENC)")"
fi
if [ -z "${DB_PASSWORD:-}" ]; then
  [ -t 0 ] || fail "Set DB_PASSWORD (the password of database user $DB_USER)."
  read -r -s -p "Password for database user $DB_USER: " DB_PASSWORD; echo
fi
DB_PASSWORD_ENC="$("$PYTHON" -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_PASSWORD")"
DATABASE_URL="mysql+pymysql://$DB_USER:$DB_PASSWORD_ENC@$DB_HOST:$DB_PORT/$DB_NAME?charset=utf8mb4"

if [ -z "$PUBLIC_URL" ]; then
  PUBLIC_URL="$(env_value SCES_PUBLIC_BASE_URL)"
  if [ -z "$PUBLIC_URL" ]; then
    ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
    PUBLIC_URL="http://${ADDRESS:-localhost}:$PORT"
  fi
fi
PUBLIC_URL="${PUBLIC_URL%/}"
case "$PUBLIC_URL" in
  # Behind an HTTPS proxy: secure cookies, and the proxy's X-Forwarded-For is the client address.
  https://*) COOKIE_SECURE=true; TRUST_PROXY=true ;;
  # Reached directly: browsers drop secure cookies over HTTP, and the address must not be spoofable.
  *) COOKIE_SECURE=false; TRUST_PROXY=false ;;
esac

ENVIRONMENT=production
[ "$VIRUS_SCANNER" = clamd ] || ENVIRONMENT=staging

SECRET_KEY="$(env_value SCES_SECRET_KEY)"
ENCRYPTION_KEY="$(env_value SCES_ENCRYPTION_KEY)"
if [ -z "$ENCRYPTION_KEY" ]; then
  say "Generating keys (first install)"
  SECRET_KEY="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  ENCRYPTION_KEY="$("$PYTHON" -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))')"
fi
keep() { local v; v="$(env_value "$1")"; echo "${v:-$2}"; }

# Values are quoted, so the file can be read by the shell and by the API alike. Settings an
# admin added by hand (mail, Web Push) are kept across upgrades.
umask 077
cat > "$ENV_FILE.new" <<EOF
# Written by install.sh. Keep a copy of this file with the backups: without
# SCES_ENCRYPTION_KEY the stored files cannot be read. Never change that key.
SCES_ENVIRONMENT='$ENVIRONMENT'
SCES_SECRET_KEY='$SECRET_KEY'
SCES_ENCRYPTION_KEY='$ENCRYPTION_KEY'
SCES_DB_PASSWORD_ENC='$DB_PASSWORD_ENC'
SCES_DATABASE_URL='$DATABASE_URL'
SCES_MIGRATION_DATABASE_URL='$DATABASE_URL'
SCES_PUBLIC_BASE_URL='$PUBLIC_URL'
SCES_COOKIE_SECURE='$COOKIE_SECURE'
SCES_TRUST_PROXY_HEADERS='$TRUST_PROXY'
SCES_STORAGE_PATH='$APP_DIR/data/files'
SCES_WEB_ROOT='$APP_DIR/frontend/dist'
SCES_VIRUS_SCANNER='$VIRUS_SCANNER'
SCES_CLAMD_HOST='127.0.0.1'
SCES_CLAMD_PORT='3310'
# Mail: smtp or gmail (docs/deployment.md, section 4). "console" sends nothing: until mail is
# set, only the first admin can get in, through the link install.sh prints. Invitations and
# sign-in codes for everyone else need mail. After a change: pm2 restart sces-api sces-worker
SCES_MAIL_PROVIDER='$(keep SCES_MAIL_PROVIDER "${MAIL_PROVIDER:-console}")'
SCES_MAIL_SENDER='$(keep SCES_MAIL_SENDER "${MAIL_SENDER:-noreply@example.org}")'
SCES_SMTP_HOST='$(keep SCES_SMTP_HOST "${SMTP_HOST:-}")'
SCES_SMTP_PORT='$(keep SCES_SMTP_PORT "${SMTP_PORT:-587}")'
SCES_SMTP_USERNAME='$(keep SCES_SMTP_USERNAME "${SMTP_USERNAME:-}")'
SCES_SMTP_PASSWORD='$(keep SCES_SMTP_PASSWORD "${SMTP_PASSWORD:-}")'
SCES_GMAIL_CLIENT_ID='$(keep SCES_GMAIL_CLIENT_ID "${GMAIL_CLIENT_ID:-}")'
SCES_GMAIL_CLIENT_SECRET='$(keep SCES_GMAIL_CLIENT_SECRET "${GMAIL_CLIENT_SECRET:-}")'
SCES_GMAIL_REFRESH_TOKEN='$(keep SCES_GMAIL_REFRESH_TOKEN "${GMAIL_REFRESH_TOKEN:-}")'
# Web Push (optional): python -m app.cli generate-keys prints a pair.
SCES_VAPID_PUBLIC_KEY='$(keep SCES_VAPID_PUBLIC_KEY "")'
SCES_VAPID_PRIVATE_KEY='$(keep SCES_VAPID_PRIVATE_KEY "")'
SCES_VAPID_SUBJECT='$(keep SCES_VAPID_SUBJECT "mailto:admin@example.org")'
EOF
mv "$ENV_FILE.new" "$ENV_FILE"
umask 022
[ "$(id -u)" = 0 ] && chown "$RUN_USER": "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "settings: $ENV_FILE"

# Python packages and the web app ----------------------------------------------------------

say "Installing the API's Python packages"
cd "$APP_DIR/backend"
[ -x .venv/bin/python ] || as_user "$PYTHON" -m venv .venv
as_user .venv/bin/pip install -q --upgrade pip
as_user .venv/bin/pip install -q .
VENV_PY="$APP_DIR/backend/.venv/bin/python"

say "Building the web app"
cd "$APP_DIR/frontend"
as_user npm ci --no-audit --no-fund --loglevel=error
as_user npm run build --silent >/dev/null
[ -f dist/index.html ] || fail "The web app build produced no dist/index.html."

# Database ---------------------------------------------------------------------------------

say "Checking the database"
cd "$APP_DIR/backend"
run_app() { as_user env -C "$APP_DIR/backend" bash -c 'set -a; . "$0"; set +a; exec "$@"' "$ENV_FILE" "$@"; }
run_app "$VENV_PY" - <<'PY' || fail "Cannot use the database (see above)."
import os, re, sys
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["SCES_DATABASE_URL"])
try:
    with engine.connect() as c:
        version = c.execute(text("select version()")).scalar()
        charset = c.execute(text("select @@character_set_database, @@collation_database")).one()
        if charset[0] != "utf8mb4":
            try:
                name = c.execute(text("select database()")).scalar()
                c.execute(text(f"alter database `{name}` character set utf8mb4 collate utf8mb4_unicode_ci"))
                charset = ("utf8mb4", "utf8mb4_unicode_ci")
            except Exception as e:  # noqa: BLE001
                sys.exit(f"The database must use utf8mb4 (Arabic text), and it is {charset[0]}: {e}")
except Exception as e:  # noqa: BLE001
    sys.exit(f"Cannot connect: {e}")
print(f"database: {version}, {charset[0]}")
m = re.match(r"(\d+)\.(\d+)", version)
major, minor = int(m[1]), int(m[2])
if "mariadb" in version.lower() and (major, minor) < (10, 6):
    sys.exit("MariaDB 10.6 or later is needed (row locking with SKIP LOCKED).")
if "mariadb" not in version.lower() and major < 8:
    sys.exit("MySQL 8 or later is needed.")
PY

say "Migrating the database"
run_app .venv/bin/alembic upgrade head

say "Setting up the district"
run_app "$VENV_PY" -m app.cli bootstrap --code "$DISTRICT_CODE" --name-en "$DISTRICT_NAME_EN" \
  --name-ar "$DISTRICT_NAME_AR" --time-zone "$TIME_ZONE"

# Virus scanner ----------------------------------------------------------------------------

clamd_up() { "$VENV_PY" -c 'import socket; s=socket.create_connection(("127.0.0.1",3310),2); s.sendall(b"zPING\0"); assert s.recv(16).startswith(b"PONG")' 2>/dev/null; }
if [ "$VIRUS_SCANNER" = clamd ]; then
  say "Setting up the virus scanner (ClamAV)"
  if ! clamd_up; then
    can_apt || fail "ClamAV's clamd must listen on 127.0.0.1:3310 (run as root to install it, or VIRUS_SCANNER=none)."
    apt_update; apt_install clamav-daemon clamav-freshclam
    CONF=/etc/clamav/clamd.conf
    grep -q '^TCPSocket' "$CONF" || echo 'TCPSocket 3310' >> "$CONF"
    grep -q '^TCPAddr' "$CONF" || echo 'TCPAddr 127.0.0.1' >> "$CONF"
    # Uploads up to the API's limit.
    grep -q '^StreamMaxLength' "$CONF" || echo 'StreamMaxLength 100M' >> "$CONF"
    if [ ! -s /var/lib/clamav/main.cvd ] && [ ! -s /var/lib/clamav/main.cld ]; then
      echo "downloading virus signatures (a few minutes the first time)"
      systemctl stop clamav-freshclam 2>/dev/null || true
      freshclam --quiet || fail "Could not download virus signatures (freshclam needs internet access)."
    fi
    systemctl enable --now clamav-freshclam >/dev/null 2>&1 || true
    systemctl enable clamav-daemon >/dev/null 2>&1 || true
    systemctl restart clamav-daemon
    for _ in $(seq 1 60); do clamd_up && break; sleep 2; done
    clamd_up || fail "clamd did not start on 127.0.0.1:3310 (journalctl -u clamav-daemon)."
  fi
  echo "clamd: running"
fi

# pm2 --------------------------------------------------------------------------------------

say "Starting with pm2"
cat > "$APP_DIR/ecosystem.config.cjs" <<EOF
// Written by install.sh. The settings come from .env, read at each start.
const fs = require("fs");
const env = {};
for (const line of fs.readFileSync("$ENV_FILE", "utf8").split("\n")) {
  const m = line.match(/^([A-Z0-9_]+)='(.*)'\$/);
  if (m) env[m[1]] = m[2];
}
const common = { cwd: "$APP_DIR/backend", env, autorestart: true, max_restarts: 20, restart_delay: 2000, time: true };
module.exports = {
  apps: [
    {
      ...common,
      name: "sces-api",
      // One process: live updates are delivered from inside it (docs/delivery-plan.md, Phase 6).
      script: "$APP_DIR/backend/.venv/bin/uvicorn",
      args: "app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips 127.0.0.1",
      interpreter: "none",
      out_file: "$APP_DIR/logs/api.log",
      error_file: "$APP_DIR/logs/api.log",
    },
    {
      ...common,
      name: "sces-worker",
      script: "$APP_DIR/backend/.venv/bin/python",
      args: "-m app.cli worker",
      interpreter: "none",
      out_file: "$APP_DIR/logs/worker.log",
      error_file: "$APP_DIR/logs/worker.log",
    },
  ],
};
EOF
[ "$(id -u)" = 0 ] && chown "$RUN_USER": "$APP_DIR/ecosystem.config.cjs"
as_user "$PM2" delete sces-api sces-worker >/dev/null 2>&1 || true
as_user "$PM2" start "$APP_DIR/ecosystem.config.cjs" >/dev/null
as_user "$PM2" save >/dev/null
if [ "$(id -u)" = 0 ]; then
  # Start again after a reboot.
  HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"
  "$PM2" startup systemd -u "$RUN_USER" --hp "$HOME_DIR" >/dev/null 2>&1 || echo "note: run 'pm2 startup' to start on boot"
fi

say "Checking it answers"
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null || fail "The API is not answering on port $PORT: pm2 logs sces-api"
curl -sf "http://127.0.0.1:$PORT/" | grep -q '<div id="root"' || fail "The web app is not served on port $PORT: pm2 logs sces-api"

if [ -n "$ADMIN_EMAIL" ]; then
  say "Inviting the first District Admin"
  run_app "$VENV_PY" -m app.cli create-admin --email "$ADMIN_EMAIL" --name "$ADMIN_NAME" --staff-id "$ADMIN_STAFF_ID" \
    || echo "(already invited, or the address is in use)"
fi

say "Installed"
cat <<EOF
Open:      $PUBLIC_URL
Processes: pm2 status   (sces-api on port $PORT, sces-worker)
Logs:      pm2 logs sces-api / pm2 logs sces-worker   (also $APP_DIR/logs)
Settings:  $ENV_FILE  (then: pm2 restart sces-api sces-worker)
EOF
if [ "$(env_value SCES_MAIL_PROVIDER)" = console ]; then
  cat <<EOF

Mail is not set up: invitations and sign-in codes are not sent. Set SCES_MAIL_PROVIDER and
its SMTP or Gmail values in $ENV_FILE, then: pm2 restart sces-api sces-worker
EOF
fi
if [ -z "$ADMIN_EMAIL" ]; then
  cat <<EOF

First admin: run once, then open the printed link to set a password and authenticator:
  cd $APP_DIR/backend && set -a && . $ENV_FILE && set +a && .venv/bin/python -m app.cli create-admin --email you@example.org --name "Your Name" --staff-id A1
EOF
fi
case "$PUBLIC_URL" in
  http://*) cat <<EOF

Note: over plain HTTP, phones cannot install the app, use the camera scanner, work offline or
get push notices; browsers allow those only over HTTPS. Put an HTTPS reverse proxy in front of
port $PORT and run again with PUBLIC_URL=https://your.domain
EOF
  ;;
esac
