#!/usr/bin/env bash
# Restore a backup into the running stack, or into a scratch stack for the monthly restore test.
#   deploy/restore.sh /srv/sces-backups/sces-20261105T011500Z.sql.gz.enc
# Afterwards, verify the audit chain:
#   docker compose run --rm api python -m app.cli verify-audit
set -euo pipefail
set -a; . ./.env; set +a
file="${1:?backup file}"

sha256sum -c "$file.sha256"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$SCES_BACKUP_PASSPHRASE_FILE" -in "$file" \
  | gunzip \
  | docker compose exec -T db sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
docker compose run --rm migrate
echo "restored: $file"
