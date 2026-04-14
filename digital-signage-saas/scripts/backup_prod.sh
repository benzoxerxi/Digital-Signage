#!/usr/bin/env bash
set -euo pipefail

# Creates a timestamped backup archive containing:
# - SQLite database (signage.db) if present
# - data/ directory
#
# Usage:
#   ./scripts/backup_prod.sh
#   BACKUP_ROOT=/srv/backups/signage ./scripts/backup_prod.sh

APP_DIR="${APP_DIR:-/var/www/digital-signage/Digital-Signage/digital-signage-saas}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/digital-signage}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEST_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

mkdir -p "${DEST_DIR}"

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
EOF

ln -sfn "${DEST_DIR}" "${BACKUP_ROOT}/latest"
echo "Backup created at: ${DEST_DIR}"
