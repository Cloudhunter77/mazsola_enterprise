#!/bin/sh
# Dump the Mazsola database next to the receipt images, so one ZFS snapshot of the
# dataset covers both. Keeps the last 14 dumps.
#
# On TrueNAS: System -> Advanced -> Cron Jobs, run daily as root:
#   sh /mnt/tank/apps/mazsola/backup.sh
#
# Restore:
#   gunzip -c mazsola-2026-09-01.sql.gz | docker exec -i <db-container> psql -U mazsola -d mazsola

set -eu

DB_CONTAINER="${DB_CONTAINER:-mazsola-db-1}"
BACKUP_DIR="${BACKUP_DIR:-/mnt/tank/apps/mazsola/backups}"
KEEP="${KEEP:-14}"

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y-%m-%d)
TARGET="$BACKUP_DIR/mazsola-$STAMP.sql.gz"

docker exec "$DB_CONTAINER" pg_dump -U mazsola -d mazsola --clean --if-exists \
  | gzip -9 > "$TARGET.tmp"

# Only replace the previous dump once this one is complete, so an interrupted run
# cannot leave a truncated file wearing today's name.
mv "$TARGET.tmp" "$TARGET"
echo "wrote $TARGET ($(du -h "$TARGET" | cut -f1))"

ls -1t "$BACKUP_DIR"/mazsola-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  echo "removing old backup $old"
  rm -f "$old"
done
