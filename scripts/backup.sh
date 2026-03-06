#!/usr/bin/env bash
#
# Automated encrypted PostgreSQL backup script.
#
# Usage: ./scripts/backup.sh
#
# Environment variables:
#   PGHOST          - PostgreSQL host (default: localhost)
#   PGPORT          - PostgreSQL port (default: 5432)
#   PGUSER          - PostgreSQL user (default: trading)
#   PGDATABASE      - PostgreSQL database (default: trading_bot)
#   PGPASSWORD      - PostgreSQL password
#   BACKUP_DIR      - Directory to store backups (default: /backups)
#   BACKUP_ENCRYPTION_KEY - age public key for encryption (required)
#   DAILY_RETENTION - Number of daily backups to keep (default: 7)
#   WEEKLY_RETENTION - Number of weekly backups to keep (default: 4)
#
# Dependencies: pg_dump, age (https://github.com/FiloSottile/age)
#

set -euo pipefail

# Configuration with defaults
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-trading}"
PGDATABASE="${PGDATABASE:-trading_bot}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
DAILY_RETENTION="${DAILY_RETENTION:-7}"
WEEKLY_RETENTION="${WEEKLY_RETENTION:-4}"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
DAY_OF_WEEK=$(date -u +"%u")  # 1=Monday, 7=Sunday

DAILY_DIR="${BACKUP_DIR}/daily"
WEEKLY_DIR="${BACKUP_DIR}/weekly"

log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $1"
}

# Validate required tools
for cmd in pg_dump age; do
    if ! command -v "$cmd" &>/dev/null; then
        log "ERROR: $cmd not found. Please install it."
        exit 1
    fi
done

# Validate encryption key
if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
    log "ERROR: BACKUP_ENCRYPTION_KEY not set. Provide an age public key."
    exit 1
fi

# Create directories
mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

DUMP_FILE="${DAILY_DIR}/${PGDATABASE}_${TIMESTAMP}.sql.gz.age"

log "Starting backup of ${PGDATABASE}@${PGHOST}:${PGPORT}"

# Dump, compress, and encrypt in a single pipeline
export PGPASSWORD="${PGPASSWORD:-}"
pg_dump \
    -h "$PGHOST" \
    -p "$PGPORT" \
    -U "$PGUSER" \
    -d "$PGDATABASE" \
    --format=plain \
    --no-owner \
    --no-privileges \
    | gzip \
    | age -r "$BACKUP_ENCRYPTION_KEY" \
    > "$DUMP_FILE"

BACKUP_SIZE=$(stat -f%z "$DUMP_FILE" 2>/dev/null || stat -c%s "$DUMP_FILE" 2>/dev/null || echo "unknown")
log "Daily backup created: ${DUMP_FILE} (${BACKUP_SIZE} bytes)"

# Weekly backup (copy Sunday's daily to weekly)
if [ "$DAY_OF_WEEK" = "7" ]; then
    WEEKLY_FILE="${WEEKLY_DIR}/${PGDATABASE}_weekly_${TIMESTAMP}.sql.gz.age"
    cp "$DUMP_FILE" "$WEEKLY_FILE"
    log "Weekly backup created: ${WEEKLY_FILE}"
fi

# Retention: prune old dailies
PRUNED_DAILY=0
while IFS= read -r old_file; do
    rm -f "$old_file"
    PRUNED_DAILY=$((PRUNED_DAILY + 1))
done < <(ls -t "${DAILY_DIR}"/*.age 2>/dev/null | tail -n +"$((DAILY_RETENTION + 1))")
[ "$PRUNED_DAILY" -gt 0 ] && log "Pruned ${PRUNED_DAILY} old daily backup(s)"

# Retention: prune old weeklies
PRUNED_WEEKLY=0
while IFS= read -r old_file; do
    rm -f "$old_file"
    PRUNED_WEEKLY=$((PRUNED_WEEKLY + 1))
done < <(ls -t "${WEEKLY_DIR}"/*.age 2>/dev/null | tail -n +"$((WEEKLY_RETENTION + 1))")
[ "$PRUNED_WEEKLY" -gt 0 ] && log "Pruned ${PRUNED_WEEKLY} old weekly backup(s)"

log "Backup complete. Daily: $(ls "${DAILY_DIR}"/*.age 2>/dev/null | wc -l | tr -d ' '), Weekly: $(ls "${WEEKLY_DIR}"/*.age 2>/dev/null | wc -l | tr -d ' ')"
