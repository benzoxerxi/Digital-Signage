#!/usr/bin/env bash
set -euo pipefail

# Restores backup from a timestamp directory created by backup_prod.sh
#
# Usage:
#   ./scripts/restore_backup.sh /var/backups/digital-signage/20260331_120000
#   APP_DIR=/var/www/.../digital-signage-saas ./scripts/restore_backup.sh /path/to/backup

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup_dir>"
  exit 1
fi

BACKUP_DIR="$1"
APP_DIR="${APP_DIR:-/var/www/digital-signage/Digital-Signage/digital-signage-saas}"

if [[ ! -d "${BACKUP_DIR}" ]]; then
  echo "Backup directory not found: ${BACKUP_DIR}"
  exit 1
fi

echo "Restoring from: ${BACKUP_DIR}"

if [[ -f "${BACKUP_DIR}/signage.db" ]]; then
  cp "${BACKUP_DIR}/signage.db" "${APP_DIR}/signage.db"
fi

if [[ -f "${BACKUP_DIR}/data.tar.gz" ]]; then
  rm -rf "${APP_DIR}/data"
  tar -xzf "${BACKUP_DIR}/data.tar.gz" -C "${APP_DIR}"
fi

echo "Restore finished."
echo "Restart application service manually after restore:"
echo "  systemctl restart signage"
