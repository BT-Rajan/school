#!/usr/bin/env bash
# Daily encrypted backup of the database and stored files (section 15: RPO 24 hours, kept 30 days).
# Run from the repository directory, for example from cron:
#   15 1 * * * cd /opt/sces && deploy/backup.sh >> /var/log/sces-backup.log 2>&1
# SCES_BACKUP_DIR should be on a separate server or disk (for example an NFS mount).
# Keep a copy of .env (it holds the encryption keys) with the backups, encrypted the same way.
set -euo pipefail
set -a; . ./.env; set +a

: "${SCES_BACKUP_DIR:?set in .env}"
: "${SCES_BACKUP_PASSPHRASE_FILE:?set in .env}"
mkdir -p "$SCES_BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$SCES_BACKUP_DIR/sces-$stamp.sql.gz.enc"

docker compose exec -T db sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers --set-gtid-purged=OFF --databases sces' \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$SCES_BACKUP_PASSPHRASE_FILE" -out "$target"

sha256sum "$target" > "$target.sha256"

# File objects are already encrypted per file; the archive is encrypted again as a whole.
# Taken after the dump, so every file the dump refers to is included.
files="$SCES_BACKUP_DIR/sces-$stamp.files.tar.enc"
docker compose exec -T api tar -C /var/lib/sces -cf - files \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$SCES_BACKUP_PASSPHRASE_FILE" -out "$files"
sha256sum "$files" > "$files.sha256"

find "$SCES_BACKUP_DIR" -name 'sces-*.enc*' -mtime +30 -delete
echo "backup written: $target and $files"
