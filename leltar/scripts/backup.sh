#!/bin/sh
# Dump the Leltár database next to the photographs, so one ZFS snapshot of the
# dataset covers both. Keeps the last 14 dumps.
#
# On TrueNAS: System -> Advanced -> Cron Jobs, run daily as root:
#   sh /mnt/tank/apps/leltar/backup.sh
#
# Restore:
#   gunzip -c leltar-2026-09-01.sql.gz | docker exec -i <db-container> psql -U leltar -d leltar

set -eu

DB_CONTAINER="${DB_CONTAINER:-leltar-db-1}"
BACKUP_DIR="${BACKUP_DIR:-/mnt/tank/apps/leltar/backups}"
KEEP="${KEEP:-14}"

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y-%m-%d)
TARGET="$BACKUP_DIR/leltar-$STAMP.sql.gz"

docker exec "$DB_CONTAINER" pg_dump -U leltar -d leltar --clean --if-exists \
  | gzip -9 > "$TARGET.tmp"

# Only replace the previous dump once this one is complete, so an interrupted run
# cannot leave a truncated file wearing today's name.
mv "$TARGET.tmp" "$TARGET"
echo "wrote $TARGET ($(du -h "$TARGET" | cut -f1))"

ls -1t "$BACKUP_DIR"/leltar-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  echo "removing old backup $old"
  rm -f "$old"
done
