#!/usr/bin/env python3
"""
One-off migration script:
- Reads tenant devices.json files
- Upserts hot operational fields into tenant_displays table
"""

import json
import os

from app import app
from config import Config
from models import TenantDisplay, User, db
from utils import normalize_command_id_for_api


def _tenant_devices_path(user_id: int) -> str:
    return os.path.join(Config.UPLOAD_FOLDER, f"tenant_{user_id}", "devices.json")


def _safe_load_json(path: str):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def migrate():
    updated = 0
    created = 0
    skipped = 0
    with app.app_context():
        users = User.query.all()
        for user in users:
            devices = _safe_load_json(_tenant_devices_path(user.id))
            if not isinstance(devices, dict):
                continue
            for device_id, row in devices.items():
                if not isinstance(row, dict):
                    skipped += 1
                    continue
                reg = TenantDisplay.query.filter_by(user_id=user.id, device_id=device_id).first()
                if not reg:
                    reg = TenantDisplay(
                        user_id=user.id,
                        device_id=device_id,
                        display_name=(row.get("name") or f"Display {str(device_id)[-4:]}")[:200],
                        first_seen_iso=(row.get("first_seen") or "")[:40] or row.get("last_seen", "")[:40],
                        last_seen_iso=(row.get("last_seen") or row.get("first_seen") or "")[:40],
                    )
                    db.session.add(reg)
                    created += 1
                reg.current_video = row.get("current_video")
                reg.command_id = normalize_command_id_for_api(row.get("command_id"))
                reg.status = (row.get("status") or "idle")[:32]
                reg.device_info_json = json.dumps(row.get("info") or {})
                reg.screenshot_requested = bool(row.get("screenshot_requested", False))
                reg.clear_cache = bool(row.get("clear_cache", False))
                reg.playback_cache_only = bool(row.get("playback_cache_only", False))
                reg.active_program_id = row.get("active_program_id")
                reg.current_video_display_name = row.get("current_video_display_name")
                reg.cache_manifest_json = json.dumps(row.get("cache_manifest") or [])
                reg.cache_manifest_file_count = row.get("cache_manifest_file_count")
                reg.cache_manifest_total_bytes = row.get("cache_manifest_total_bytes")
                reg.cache_manifest_updated_at = row.get("cache_manifest_updated_at")
                reg.cache_delete_keys_json = json.dumps(row.get("cache_delete_keys") or [])
                reg.screenshot_data = row.get("screenshot_data")
                reg.screenshot_timestamp = row.get("screenshot_timestamp")
                if isinstance(row.get("download_progress"), dict):
                    reg.download_progress_json = json.dumps(row["download_progress"])
                updated += 1
        db.session.commit()
    print(f"Migration complete. rows_updated={updated} rows_created={created} rows_skipped={skipped}")


if __name__ == "__main__":
    migrate()
