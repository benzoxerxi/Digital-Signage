#!/usr/bin/env bash
set -euo pipefail

# Creates a timestamped backup archive containing:
# - PostgreSQL dump (preferred) when DATABASE_URL is available
# - SQLite database (signage.db) fallback
# - data/ directory
#
# Usage:
#   ./scripts/backup_prod.sh
#   BACKUP_ROOT=/srv/backups/signage ./scripts/backup_prod.sh

APP_DIR="${APP_DIR:-/var/www/digital-signage/Digital-Signage/digital-signage-saas}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/digital-signage}"
ENV_FILE="${ENV_FILE:-/etc/signage.env}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEST_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

mkdir -p "${DEST_DIR}"

if [[ -z "${DATABASE_URL:-}" && -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -n "${DATABASE_URL:-}" ]]; then
  pg_dump "${DATABASE_URL}" --format=custom --file "${DEST_DIR}/postgres.dump"
fi

if [[ -f "${APP_DIR}/signage.db" ]]; then
  cp "${APP_DIR}/signage.db" "${DEST_DIR}/signage.db"
fi

if [[ -d "${APP_DIR}/data" ]]; then
  tar -czf "${DEST_DIR}/data.tar.gz" -C "${APP_DIR}" data
fi

cat > "${DEST_DIR}/manifest.txt" <<EOF
created_at=${TIMESTAMP}
app_dir=${APP_DIR}
hostname=$(hostname)
database_url_present=$([[ -n "${DATABASE_URL:-}" ]] && echo yes || echo no)
EOF

ln -sfn "${DEST_DIR}" "${BACKUP_ROOT}/latest"
echo "Backup created at: ${DEST_DIR}"
