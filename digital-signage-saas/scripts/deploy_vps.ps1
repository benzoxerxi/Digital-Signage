# Windows helper: VPS deploy is implemented in deploy_vps.sh (rsync + ssh).
# Run ONE of:
#   wsl -e bash scripts/deploy_vps.sh
#   # or Git Bash:
#   bash scripts/deploy_vps.sh
#
# Before first deploy, on the server:
#   1. Copy deploy/gunicorn.service.example to /etc/systemd/system/signage.service
#   2. Create /etc/signage.env (SECRET_KEY, DATABASE_URL, DATA_DIR=/var/lib/signage-data)
#   3. sudo mkdir -p /var/lib/signage-data && sudo chown www-data:www-data /var/lib/signage-data
#   4. sudo systemctl daemon-reload && sudo systemctl enable --now signage
#   5. Optional: nginx from deploy/nginx-signage.conf.example
#
# Environment (optional, in Git Bash / WSL):
#   $env:DEPLOY_USER = "root"
#   bash scripts/deploy_vps.sh --init-remote

Write-Host "Use Git Bash or WSL:  bash scripts/deploy_vps.sh" -ForegroundColor Yellow
Write-Host "Default host: 94.250.201.69  (override: `$env:DEPLOY_HOST)" -ForegroundColor Gray
