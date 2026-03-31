# CI/CD and Backup Guide

This guide sets up:
- GitHub Actions CI/CD: `push main -> test -> deploy`
- Scheduled backups for `signage.db` and `data/`
- Restore and restore-test procedures

## 1) GitHub Actions CI/CD

Workflow file:
- `.github/workflows/signage-cicd.yml`

Pipeline behavior:
1. On push to `main` (for `digital-signage-saas/**`), run:
   - dependency install
   - Python compile smoke check
   - `pytest` if `tests/` exists
2. If test job passes, deploy over SSH:
   - `git pull --ff-only origin main`
   - `systemctl restart signage`
   - `systemctl reload nginx`

### Required GitHub Secrets

In GitHub repo settings, add:
- `VPS_HOST` (example: `94.250.201.69`)
- `VPS_USER` (example: `root`)
- `VPS_SSH_KEY` (private key that can SSH to VPS)

## 2) Backup scripts

Scripts:
- `scripts/backup_prod.sh`
- `scripts/restore_backup.sh`
- `scripts/test_restore.sh`

Recommended backup location:
- `/var/backups/digital-signage/<timestamp>/`
- symlink: `/var/backups/digital-signage/latest`

### One-time setup on VPS

```bash
cd /var/www/digital-signage/Digital-Signage/digital-signage-saas
chmod +x scripts/*.sh
mkdir -p /var/backups/digital-signage
```

### Run manual backup

```bash
cd /var/www/digital-signage/Digital-Signage/digital-signage-saas
./scripts/backup_prod.sh
```

## 3) Schedule regular backups (cron)

Example: every day at 03:20

```bash
crontab -e
```

Add:

```cron
20 3 * * * /var/www/digital-signage/Digital-Signage/digital-signage-saas/scripts/backup_prod.sh >> /var/log/signage-backup.log 2>&1
```

Optional cleanup policy (keep 14 days):

```cron
50 3 * * * find /var/backups/digital-signage -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} \; >> /var/log/signage-backup.log 2>&1
```

## 4) Restore procedure

1. Pick a backup:
```bash
ls -lah /var/backups/digital-signage
```
2. Restore:
```bash
cd /var/www/digital-signage/Digital-Signage/digital-signage-saas
./scripts/restore_backup.sh /var/backups/digital-signage/<timestamp>
systemctl restart signage
```

## 5) Restore test (recommended weekly)

Run restore test without touching production files:

```bash
cd /var/www/digital-signage/Digital-Signage/digital-signage-saas
./scripts/test_restore.sh /var/backups/digital-signage/latest
```

If this command exits successfully, backup artifacts are restorable.
