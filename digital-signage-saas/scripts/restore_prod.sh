#!/usr/bin/env bash
set -euo pipefail

# Restore backup produced by backup_prod.sh
# Usage:
#   ./scripts/restore_prod.sh /var/backups/digital-signage/20260414_120000

BACKUP_DIR="${1:-}"
APP_DIR="${APP_DIR:-/var/www/digital-signage/Digital-Signage/digital-signage-saas}"
ENV_FILE="${ENV_FILE:-/etc/signage.env}"

if [[ -z "${BACKUP_DIR}" || ! -d "${BACKUP_DIR}" ]]; then
  echo "Usage: $0 <backup_dir>"
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" && -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -f "${BACKUP_DIR}/postgres.dump" ]]; then
  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "postgres.dump found but DATABASE_URL is not set"
    exit 1
  fi
  pg_restore --clean --if-exists --no-owner --dbname "${DATABASE_URL}" "${BACKUP_DIR}/postgres.dump"
fi

if [[ -f "${BACKUP_DIR}/signage.db" ]]; then
  cp "${BACKUP_DIR}/signage.db" "${APP_DIR}/signage.db"
fi

if [[ -f "${BACKUP_DIR}/data.tar.gz" ]]; then
  tar -xzf "${BACKUP_DIR}/data.tar.gz" -C "${APP_DIR}"
fi

echo "Restore complete from: ${BACKUP_DIR}"
