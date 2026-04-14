#!/usr/bin/env bash
# Deploy Digital Signage SaaS to a Linux VPS (e.g. Contabo).
# Run from Git Bash, WSL, or macOS/Linux — NOT from plain CMD.
#
# Prerequisites on YOUR machine: ssh, rsync
# Prerequisites on SERVER (one-time): Python 3.10+, venv, PostgreSQL recommended,
#   optional: nginx, certbot. Create REMOTE_DIR and venv first, or use --init-remote.
#
# Usage:
#   export DEPLOY_USER=root                    # or ubuntu, debian, etc.
#   export SSH_KEY=~/.ssh/id_rsa             # optional
#   ./scripts/deploy_vps.sh                  # uses defaults below
#   ./scripts/deploy_vps.sh --init-remote    # remote: apt install deps, venv, dirs (Debian/Ubuntu)
#
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:-94.250.201.69}"
DEPLOY_USER="${DEPLOY_USER:-root}"
REMOTE_DIR="${REMOTE_DIR:-/var/www/digital-signage-saas}"
SERVICE_NAME="${SERVICE_NAME:-signage}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8000/api/status}"
INIT_REMOTE=false

for arg in "$@"; do
  [[ "$arg" == "--init-remote" ]] && INIT_REMOTE=true
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
[[ -n "${SSH_KEY:-}" ]] && SSH_OPTS+=(-i "$SSH_KEY")
RSYNC_E="ssh ${SSH_OPTS[*]}"

echo "==> Deploy host: $DEPLOY_USER@$DEPLOY_HOST"
echo "==> Remote dir:  $REMOTE_DIR"

if $INIT_REMOTE; then
  echo "==> Running remote bootstrap (Debian/Ubuntu)..."
  ssh "${SSH_OPTS[@]}" "$DEPLOY_USER@$DEPLOY_HOST" bash -s << REMOTE_BOOT
set -e
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip rsync nginx curl
mkdir -p "$REMOTE_DIR"
if [[ ! -d "$REMOTE_DIR/venv" ]]; then
  python3 -m venv "$REMOTE_DIR/venv"
fi
chown -R www-data:www-data "$REMOTE_DIR" 2>/dev/null || true
echo "Bootstrap done. Install PostgreSQL separately if needed; set DATABASE_URL in /etc/signage.env"
REMOTE_BOOT
fi

echo "==> Rsync project (excluding venv, .git, db, logs)..."
rsync -avz --delete \
  --exclude '.git/' \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'signage.db' \
  --exclude '.env' \
  --exclude 'debug-*.log' \
  --exclude 'data/' \
  -e "$RSYNC_E" \
  "$ROOT/" \
  "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_DIR/"

echo "==> Remote: pip install + restart service..."
ssh "${SSH_OPTS[@]}" "$DEPLOY_USER@$DEPLOY_HOST" bash -s << REMOTE_CMD
set -e
cd "$REMOTE_DIR"
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
if [[ -f "manage.py" ]]; then
  ./venv/bin/flask db upgrade || true
fi
chown -R www-data:www-data "$REMOTE_DIR" 2>/dev/null || true
if systemctl list-units --type=service --all | grep -q "$SERVICE_NAME.service"; then
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl status "$SERVICE_NAME" --no-pager || true
else
  echo "No systemd unit '$SERVICE_NAME'. Install deploy/gunicorn.service.example → /etc/systemd/system/${SERVICE_NAME}.service"
  echo "Quick test: cd $REMOTE_DIR && ./venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 app:app"
fi
if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 10 "$HEALTHCHECK_URL" >/dev/null
fi
REMOTE_CMD

echo "==> Done."
