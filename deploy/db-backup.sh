#!/usr/bin/env bash
# Backups of the database (pre-pilot review 10.11.2026, p. 18; deploy/README.md, «Бэкапы»).
# Runs inside the db container: docker compose exec -T db db-backup.sh [backup|check]
#   backup — a dump of the database into $BACKUP_DIR, the ones older than $KEEP_DAYS deleted;
#   check  — the latest dump restored into a scratch database, its tables counted, the scratch dropped.
# A nonzero exit means the backup or the check failed: cron mails it, or the operator sees it.
set -euo pipefail

DB="${DB:-franchise}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
export PGUSER="${PGUSER:-postgres}"

backup() {
  local name tmp
  name="$BACKUP_DIR/$DB-$(date -u +%Y%m%d-%H%M%S).dump"
  tmp="$name.part"
  pg_dump --format=custom --file="$tmp" "$DB"
  mv "$tmp" "$name"
  find "$BACKUP_DIR" -maxdepth 1 -name "$DB-*.dump" -mtime "+$KEEP_DAYS" -delete
  echo "backup: $name ($(du -h "$name" | cut -f1))"
}

check() {
  local latest tables live restored
  latest="$(ls -1t "$BACKUP_DIR"/"$DB"-*.dump 2>/dev/null | head -n 1 || true)"
  if [ -z "$latest" ]; then
    echo "check: no dump in $BACKUP_DIR" >&2
    exit 1
  fi
  scratch="${DB}_restore_check"  # global: the EXIT trap drops it whatever happens
  dropdb --if-exists "$scratch" 2>/dev/null
  createdb "$scratch"
  trap 'dropdb --if-exists "$scratch"' EXIT
  pg_restore --exit-on-error --dbname="$scratch" "$latest"
  tables="SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
  live="$(psql -Atc "$tables" "$DB")"
  restored="$(psql -Atc "$tables" "$scratch")"
  if [ "$live" != "$restored" ]; then
    echo "check: $latest has $restored tables, the database $live" >&2
    exit 1
  fi
  echo "check: $latest restores, $restored tables," \
    "$(psql -Atc 'SELECT count(*) FROM tenants' "$scratch") networks," \
    "$(psql -Atc 'SELECT count(*) FROM import_batches' "$scratch") files"
}

case "${1:-backup}" in
  backup) backup ;;
  check) check ;;
  *) echo "usage: db-backup.sh [backup|check]" >&2; exit 2 ;;
esac
