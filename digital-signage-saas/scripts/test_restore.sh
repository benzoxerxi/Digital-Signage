#!/usr/bin/env bash
set -euo pipefail

# Validates that a backup can be restored without touching production files.
# It restores backup artifacts into a temporary directory and runs integrity checks.
#
# Usage:
#   ./scripts/test_restore.sh /var/backups/digital-signage/latest

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup_dir>"
  exit 1
fi

BACKUP_DIR="$1"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "Testing restore from: ${BACKUP_DIR}"
echo "Temp dir: ${TMP_DIR}"

if [[ -f "${BACKUP_DIR}/signage.db" ]]; then
  cp "${BACKUP_DIR}/signage.db" "${TMP_DIR}/signage.db"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "${TMP_DIR}/signage.db" "PRAGMA integrity_check;" | grep -q "ok"
  fi
fi

if [[ -f "${BACKUP_DIR}/data.tar.gz" ]]; then
  tar -xzf "${BACKUP_DIR}/data.tar.gz" -C "${TMP_DIR}"
  test -d "${TMP_DIR}/data"
fi

echo "Restore test passed."
