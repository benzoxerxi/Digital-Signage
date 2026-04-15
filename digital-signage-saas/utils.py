"""
Utility functions shared across the application
This prevents circular imports
"""
import os
import json
import hashlib
import threading
import tempfile
import shutil
import uuid
from datetime import datetime
from flask_login import current_user
from config import Config

# Global lock for device operations
device_lock = threading.Lock()

# In-memory only: device-reported current video (from heartbeat). Not persisted to disk.
# Key: (user_id, device_id) -> reported_current_video string
_reported_current_video_cache = {}
# In-memory: display name for current video (so device can show Drive name). Key: (user_id, device_id) -> str
_current_video_display_name_cache = {}
# In-memory: device-reported display name (echoed in heartbeat). Not persisted. Key: (user_id, device_id) -> str
_reported_current_video_name_cache = {}


def normalize_command_id_for_api(val):
    if val is None:
        return ''
    if isinstance(val, int):
        return str(val) if val else ''
    return str(val).strip()[:40]


def new_playback_command_id():
    return str(uuid.uuid4())


def bump_playback_state_version(row):
    row.state_version = int(row.state_version or 0) + 1


def device_row_to_dict(row):
    """Build device dict compatible with dashboard / playback (from TenantDisplay ORM row)."""
    try:
        info = json.loads(row.device_info_json) if row.device_info_json else {}
    except Exception:
        info = {}
    cmd = normalize_command_id_for_api(row.command_id)
    d = {
        'id': row.device_id,
        'name': row.display_name,
        'first_seen': row.first_seen_iso,
        'last_seen': row.last_seen_iso,
        'current_video': row.current_video,
        'command_id': cmd,
        'state_version': int(row.state_version or 0),
        'status': (row.status or 'idle')[:32],
        'info': info if isinstance(info, dict) else {},
        'screenshot_requested': bool(row.screenshot_requested),
        'clear_cache': bool(row.clear_cache),
        'playback_cache_only': bool(row.playback_cache_only),
    }
    if row.active_program_id:
        d['active_program_id'] = row.active_program_id
    if row.current_video_display_name:
        d['current_video_display_name'] = row.current_video_display_name
    if row.cache_manifest_json:
        try:
            d['cache_manifest'] = json.loads(row.cache_manifest_json)
        except Exception:
            d['cache_manifest'] = []
    else:
        d['cache_manifest'] = []
    d['cache_manifest_file_count'] = row.cache_manifest_file_count
    d['cache_manifest_total_bytes'] = row.cache_manifest_total_bytes
    d['cache_manifest_updated_at'] = row.cache_manifest_updated_at
    if row.cache_delete_keys_json:
        try:
            d['cache_delete_keys'] = json.loads(row.cache_delete_keys_json)
        except Exception:
            d['cache_delete_keys'] = []
    else:
        d['cache_delete_keys'] = []
    if row.download_progress_json:
        try:
            parsed = json.loads(row.download_progress_json)
            if isinstance(parsed, dict):
                d['download_progress'] = parsed
        except Exception:
            pass
    if row.screenshot_data:
        d['screenshot_data'] = row.screenshot_data
    if row.screenshot_timestamp:
        d['screenshot_timestamp'] = row.screenshot_timestamp
    return d


def _import_legacy_devices_json_if_needed(user_id):
    """One-time style merge: create TenantDisplay rows from stale devices.json when missing in DB."""
    from models import TenantDisplay, db
    try:
        legacy = load_json_file('devices.json', {}, user_id)
        if not legacy:
            return
        changed = False
        for did, dd in list(legacy.items()):
            if not isinstance(dd, dict):
                continue
            exists = TenantDisplay.query.filter_by(user_id=user_id, device_id=did).first()
            if exists:
                continue
            db.session.add(TenantDisplay(
                user_id=user_id,
                device_id=did,
                display_name=(dd.get('name') or f'Display {str(did)[-4:]}')[:200],
                first_seen_iso=(dd.get('first_seen') or datetime.now().isoformat())[:40],
                last_seen_iso=(dd.get('last_seen') or dd.get('first_seen') or datetime.now().isoformat())[:40],
                current_video=dd.get('current_video'),
                command_id=normalize_command_id_for_api(dd.get('command_id')) or '',
                state_version=0,
                status=(dd.get('status') or 'idle')[:32],
                device_info_json=json.dumps(dd.get('info') or {}),
                screenshot_requested=bool(dd.get('screenshot_requested', False)),
                clear_cache=bool(dd.get('clear_cache', False)),
                playback_cache_only=bool(dd.get('playback_cache_only', False)),
                active_program_id=dd.get('active_program_id'),
                cache_manifest_json=json.dumps(dd.get('cache_manifest') if isinstance(dd.get('cache_manifest'), list) else []),
                cache_manifest_file_count=dd.get('cache_manifest_file_count'),
                cache_manifest_total_bytes=dd.get('cache_manifest_total_bytes'),
                cache_manifest_updated_at=dd.get('cache_manifest_updated_at'),
                cache_delete_keys_json=json.dumps(dd.get('cache_delete_keys') or []),
                current_video_display_name=dd.get('current_video_display_name'),
                screenshot_data=dd.get('screenshot_data'),
                screenshot_timestamp=dd.get('screenshot_timestamp'),
                download_progress_json=json.dumps(dd['download_progress']) if isinstance(dd.get('download_progress'), dict) else None,
            ))
            changed = True
        if changed:
            db.session.commit()
    except Exception:
        try:
            from models import db as _db
            _db.session.rollback()
        except Exception:
            pass


def _normalized_download_progress(device_data):
    dp = device_data.get('download_progress')
    if not isinstance(dp, dict):
        return None
    try:
        status = str(dp.get('status') or 'downloading')
        updated_at_ms = int(dp.get('updated_at_ms') or 0)
        age_ms = int(datetime.now().timestamp() * 1000) - updated_at_ms if updated_at_ms else 0
        # Hide stale in-progress records, keep "completed" for a short window.
        if status not in ('completed', 'failed') and updated_at_ms and age_ms > 120000:
            return None
        if status in ('completed', 'failed') and updated_at_ms and age_ms > 180000:
            return None
        return {
            'filename': str(dp.get('filename') or ''),
            'name': str(dp.get('name') or ''),
            'bytes_read': int(dp.get('bytes_read') or 0),
            'total_bytes': int(dp.get('total_bytes') or 0),
            'percent': float(dp.get('percent') or 0.0),
            'status': status,
            'updated_at_ms': updated_at_ms,
        }
    except Exception:
        return None


def get_tenant_path(user_id=None):
    """Get the base path for a tenant's data"""
    if user_id is None:
        if not current_user.is_authenticated:
            return None
        user_id = current_user.id
    
    tenant_id = f"tenant_{user_id}"
    return os.path.join(Config.UPLOAD_FOLDER, tenant_id)


def get_content_folder(user_id=None):
    """Get content upload folder for tenant"""
    tenant_path = get_tenant_path(user_id)
    if not tenant_path:
        return None
    return os.path.join(tenant_path, 'content')


def get_data_file_path(filename, user_id=None):
    """Get path to a data file for tenant"""
    tenant_path = get_tenant_path(user_id)
    if not tenant_path:
        return None
    return os.path.join(tenant_path, filename)


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def get_file_hash(filepath):
    """Calculate MD5 hash of file"""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def load_json_file(filename, default, user_id=None):
    """Load JSON file for specific tenant"""
    filepath = get_data_file_path(filename, user_id)
    if not filepath or not os.path.exists(filepath):
        return default
    backup_path = filepath + '.bak'
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default


def save_json_file(filename, data, user_id=None):
    """Save JSON file for specific tenant"""
    filepath = get_data_file_path(filename, user_id)
    if not filepath:
        return False
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_fd = None
    tmp_path = None
    backup_path = filepath + '.bak'
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(filepath) + '.',
            suffix='.tmp',
            dir=os.path.dirname(filepath),
            text=True,
        )
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            tmp_fd = None
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(filepath):
            shutil.copy2(filepath, backup_path)
        os.replace(tmp_path, filepath)
        return True
    except Exception:
        return False
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def get_storage_usage(user_id=None):
    """Calculate total storage used by tenant in GB"""
    content_folder = get_content_folder(user_id)
    if not content_folder or not os.path.exists(content_folder):
        return 0.0
    
    total_size = 0
    for filename in os.listdir(content_folder):
        filepath = os.path.join(content_folder, filename)
        if os.path.isfile(filepath):
            total_size += os.path.getsize(filepath)
    
    return total_size / (1024 ** 3)  # Convert to GB


def log_activity(event_type, event_data, user_id=None):
    """Log user activity"""
    from models import db, ActivityLog
    from flask import request
    
    if user_id is None:
        if not current_user.is_authenticated:
            return
        user_id = current_user.id
    
    try:
        activity = ActivityLog(
            user_id=user_id,
            event_type=event_type,
            event_data=json.dumps(event_data),
            ip_address=request.remote_addr if request else None
        )
        db.session.add(activity)
        db.session.commit()
    except:
        pass  # Don't fail if logging fails


def _get_removed_devices(user_id):
    """List of device_ids that were removed from panel; they must not be re-added by heartbeat until re-connected from setup."""
    data = load_json_file('removed_devices.json', [], user_id)
    return set(data) if isinstance(data, list) else set()


def add_removed_device(user_id, device_id):
    """Mark device as removed so heartbeat does not re-add it until re-connected from setup."""
    removed = _get_removed_devices(user_id)
    removed.add(device_id)
    save_json_file('removed_devices.json', list(removed), user_id)


def _clear_removed_device(user_id, device_id):
    removed = _get_removed_devices(user_id)
    removed.discard(device_id)
    save_json_file('removed_devices.json', list(removed), user_id)


def set_current_video_display_name(user_id, device_id, name):
    """Set display name for current video on device (e.g. Drive file name). In-memory only."""
    key = (user_id, device_id)
    if name:
        _current_video_display_name_cache[key] = name
    else:
        _current_video_display_name_cache.pop(key, None)


def get_current_video_display_name(user_id, device_id):
    """Get display name for current video (for playback state response to APK)."""
    return _current_video_display_name_cache.get((user_id, device_id))


def _upsert_tenant_display_registry(user_id, device_id, display_name, first_seen_iso, last_seen_iso):
    """Mirror display identity in DB so the panel list survives loss of devices.json."""
    from models import TenantDisplay, db
    name = (display_name or f'Display {str(device_id)[-4:]}')[:200]
    fs = (first_seen_iso or datetime.now().isoformat())[:40]
    ls = (last_seen_iso or datetime.now().isoformat())[:40]
    row = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
    if row:
        row.display_name = name
        row.last_seen_iso = ls
    else:
        db.session.add(TenantDisplay(
            user_id=user_id,
            device_id=device_id,
            display_name=name,
            first_seen_iso=fs,
            last_seen_iso=ls,
        ))
    db.session.commit()


def _sync_hot_state_to_registry_row(user_id, device_id, device_data):
    """Persist device state dict onto TenantDisplay (used by legacy callers that still pass dict)."""
    from models import TenantDisplay, db
    row = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
    if not row:
        _upsert_tenant_display_registry(
            user_id,
            device_id,
            device_data.get('name'),
            device_data.get('first_seen'),
            device_data.get('last_seen'),
        )
        row = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
        if not row:
            return
    row.current_video = device_data.get('current_video')
    row.command_id = normalize_command_id_for_api(device_data.get('command_id'))
    row.status = (device_data.get('status') or 'idle')[:32]
    row.device_info_json = json.dumps(device_data.get('info') or {})
    row.screenshot_requested = bool(device_data.get('screenshot_requested', False))
    row.clear_cache = bool(device_data.get('clear_cache', False))
    row.playback_cache_only = bool(device_data.get('playback_cache_only', False))
    row.current_video_display_name = device_data.get('current_video_display_name')
    if 'active_program_id' in device_data:
        row.active_program_id = device_data.get('active_program_id')
    if 'screenshot_data' in device_data:
        row.screenshot_data = device_data.get('screenshot_data')
    if 'screenshot_timestamp' in device_data:
        row.screenshot_timestamp = device_data.get('screenshot_timestamp')
    cache_manifest = device_data.get('cache_manifest')
    row.cache_manifest_json = json.dumps(cache_manifest if isinstance(cache_manifest, list) else [])
    row.cache_manifest_file_count = device_data.get('cache_manifest_file_count')
    row.cache_manifest_total_bytes = device_data.get('cache_manifest_total_bytes')
    row.cache_manifest_updated_at = device_data.get('cache_manifest_updated_at')
    row.cache_delete_keys_json = json.dumps(device_data.get('cache_delete_keys') or [])
    dp = device_data.get('download_progress')
    if isinstance(dp, dict):
        row.download_progress_json = json.dumps(dp)
    elif dp is None and 'download_progress' in device_data:
        row.download_progress_json = None
    db.session.commit()


def _overlay_hot_state_from_registry(row, device_data):
    """Merge DB runtime state over JSON fallback state (legacy JSON path only)."""
    if not row:
        return device_data
    merged = dict(device_data)
    merged['current_video'] = row.current_video
    merged['command_id'] = normalize_command_id_for_api(row.command_id) or normalize_command_id_for_api(merged.get('command_id'))
    merged['status'] = row.status or merged.get('status', 'idle')
    try:
        merged['info'] = json.loads(row.device_info_json) if row.device_info_json else (merged.get('info') or {})
    except Exception:
        merged['info'] = merged.get('info') or {}
    merged['screenshot_requested'] = bool(row.screenshot_requested)
    merged['clear_cache'] = bool(row.clear_cache)
    merged['playback_cache_only'] = bool(row.playback_cache_only)
    if row.active_program_id:
        merged['active_program_id'] = row.active_program_id
    elif row.active_program_id is None and 'active_program_id' in merged:
        merged.pop('active_program_id', None)
    if row.current_video_display_name:
        merged['current_video_display_name'] = row.current_video_display_name
    if row.cache_manifest_json:
        try:
            merged['cache_manifest'] = json.loads(row.cache_manifest_json)
        except Exception:
            merged['cache_manifest'] = []
    merged['cache_manifest_file_count'] = row.cache_manifest_file_count
    merged['cache_manifest_total_bytes'] = row.cache_manifest_total_bytes
    merged['cache_manifest_updated_at'] = row.cache_manifest_updated_at
    if row.cache_delete_keys_json:
        try:
            merged['cache_delete_keys'] = json.loads(row.cache_delete_keys_json)
        except Exception:
            merged['cache_delete_keys'] = []
    if row.screenshot_data is not None:
        merged['screenshot_data'] = row.screenshot_data
    if row.screenshot_timestamp:
        merged['screenshot_timestamp'] = row.screenshot_timestamp
    if row.download_progress_json:
        try:
            merged['download_progress'] = json.loads(row.download_progress_json)
        except Exception:
            pass
    return merged


def delete_tenant_display_registry(user_id, device_id):
    from models import TenantDisplay, db
    try:
        TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).delete()
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def merge_registry_into_devices_dict(user_id, devices):
    """Legacy: merge DB into devices dict. DB is source of truth — import stale JSON rows then return False."""
    _import_legacy_devices_json_if_needed(user_id)
    return False


def sync_device_registry_row(user_id, device_id, device_row):
    """Keep tenant_displays in sync after panel edits (e.g. rename)."""
    if not device_row:
        return
    try:
        _upsert_tenant_display_registry(
            user_id,
            device_id,
            device_row.get('name'),
            device_row.get('first_seen', datetime.now().isoformat()),
            device_row.get('last_seen', datetime.now().isoformat()),
        )
    except Exception:
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass


def sync_devices_hot_state(user_id, devices, only_device_ids=None):
    """Persist one/all device rows to DB hot-state columns."""
    target_ids = only_device_ids or list(devices.keys())
    for did in target_ids:
        row = devices.get(did)
        if not isinstance(row, dict):
            continue
        try:
            _sync_hot_state_to_registry_row(user_id, did, row)
        except Exception:
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass


def _append_device_status_row(result, user_id, device_id, device_data, now):
    """Single device dict -> row with online/reported_* fields (same as previous get_all_devices loop)."""
    try:
        row = dict(device_data)
        row['id'] = device_id
        row['reported_current_video'] = _reported_current_video_cache.get((user_id, device_id))
        row['reported_current_video_name'] = (
            _reported_current_video_name_cache.get((user_id, device_id))
            or device_data.get('current_video_display_name')
            or get_current_video_display_name(user_id, device_id)
        )
        last_seen = datetime.fromisoformat(device_data.get('last_seen', now.isoformat()))
        seconds_ago = (now - last_seen).total_seconds()
        row['online'] = seconds_ago <= Config.DEVICE_TIMEOUT
        if row['online']:
            row['last_seen_ago'] = int(seconds_ago)
        else:
            row['last_seen_ago'] = None
        cm = device_data.get('cache_manifest')
        row['cache_manifest'] = cm if isinstance(cm, list) else None
        row['cache_manifest_updated_at'] = device_data.get('cache_manifest_updated_at')
        row['cache_manifest_file_count'] = device_data.get('cache_manifest_file_count')
        if row['cache_manifest_file_count'] is None and isinstance(cm, list):
            row['cache_manifest_file_count'] = len(cm)
        row['cache_manifest_total_bytes'] = device_data.get('cache_manifest_total_bytes')
        if row['cache_manifest_total_bytes'] is None and isinstance(cm, list):
            tb = 0
            for x in cm:
                if isinstance(x, dict):
                    try:
                        tb += int(x.get('s') or 0)
                    except (TypeError, ValueError):
                        pass
            row['cache_manifest_total_bytes'] = tb
        row['download_progress'] = _normalized_download_progress(device_data)
        result.append(row)
    except Exception:
        row = dict(device_data)
        row['id'] = device_id
        row['reported_current_video'] = _reported_current_video_cache.get((user_id, device_id))
        row['reported_current_video_name'] = (
            _reported_current_video_name_cache.get((user_id, device_id))
            or device_data.get('current_video_display_name')
            or get_current_video_display_name(user_id, device_id)
        )
        row['online'] = False
        row['last_seen_ago'] = None
        cm = device_data.get('cache_manifest')
        row['cache_manifest'] = cm if isinstance(cm, list) else None
        row['cache_manifest_updated_at'] = device_data.get('cache_manifest_updated_at')
        row['cache_manifest_file_count'] = device_data.get('cache_manifest_file_count')
        if row['cache_manifest_file_count'] is None and isinstance(cm, list):
            row['cache_manifest_file_count'] = len(cm)
        row['cache_manifest_total_bytes'] = device_data.get('cache_manifest_total_bytes')
        if row['cache_manifest_total_bytes'] is None and isinstance(cm, list):
            tb = 0
            for x in cm:
                if isinstance(x, dict):
                    try:
                        tb += int(x.get('s') or 0)
                    except (TypeError, ValueError):
                        pass
            row['cache_manifest_total_bytes'] = tb
        row['download_progress'] = _normalized_download_progress(device_data)
        result.append(row)


def update_device_heartbeat(device_id, device_name=None, device_info=None, user_id=None, from_setup=False, reported_current_video=None, reported_current_video_name=None, reported_cache_manifest=None, reported_download_progress=None):
    """Update device information for tenant. If device was removed from panel and from_setup is False, returns None (caller should respond with removed=True to APK).
    reported_current_video / reported_current_video_name: from device (APK heartbeat). In memory only; not persisted to disk.
    reported_cache_manifest: optional JSON array string from APK; stored on device row as cache_manifest (last reported disk cache inventory).
    reported_download_progress: optional JSON object string from APK with active download state."""
    if user_id is None:
        user_id = current_user.id

    is_new_device = False
    with device_lock:
        removed = _get_removed_devices(user_id)
        if from_setup:
            _clear_removed_device(user_id, device_id)
        elif device_id in removed:
            return None

    from models import TenantDisplay, db
    _import_legacy_devices_json_if_needed(user_id)
    legacy_all = load_json_file('devices.json', {}, user_id)
    legacy = legacy_all.get(device_id) if isinstance(legacy_all, dict) else None

    try:
        row = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
        now = datetime.now()
        now_iso = now.isoformat()[:40]
        if row is None:
            is_new_device = True
            display_name = device_name or (legacy or {}).get('name')
            if not display_name:
                display_name = f'Display {TenantDisplay.query.filter_by(user_id=user_id).count() + 1}'
            fs = ((legacy or {}).get('first_seen') or now_iso)[:40]
            row = TenantDisplay(
                user_id=user_id,
                device_id=device_id,
                display_name=(display_name or 'Display')[:200],
                first_seen_iso=fs,
                last_seen_iso=now_iso,
                command_id='',
                state_version=0,
                status='idle',
                device_info_json=json.dumps((legacy or {}).get('info') or {}),
            )
            if legacy:
                row.current_video = legacy.get('current_video')
                row.command_id = normalize_command_id_for_api(legacy.get('command_id'))
                row.status = (legacy.get('status') or 'idle')[:32]
                row.screenshot_requested = bool(legacy.get('screenshot_requested', False))
                row.clear_cache = bool(legacy.get('clear_cache', False))
                row.playback_cache_only = bool(legacy.get('playback_cache_only', False))
                row.active_program_id = legacy.get('active_program_id')
                row.current_video_display_name = legacy.get('current_video_display_name')
                if isinstance(legacy.get('cache_manifest'), list):
                    row.cache_manifest_json = json.dumps(legacy.get('cache_manifest'))
                row.cache_delete_keys_json = json.dumps(legacy.get('cache_delete_keys') or [])
            db.session.add(row)
            db.session.flush()

        row.last_seen_iso = now_iso
        if device_name:
            row.display_name = (device_name or row.display_name)[:200]
        try:
            info = json.loads(row.device_info_json) if row.device_info_json else {}
        except Exception:
            info = {}
        if device_info:
            info.update(device_info)
        row.device_info_json = json.dumps(info)

        key = (user_id, device_id)
        if reported_current_video is not None:
            _reported_current_video_cache[key] = reported_current_video if reported_current_video else None
        if reported_current_video_name is not None:
            _reported_current_video_name_cache[key] = reported_current_video_name if reported_current_video_name else None

        if reported_cache_manifest is not None:
            try:
                import json as _json
                parsed = _json.loads(reported_cache_manifest) if isinstance(reported_cache_manifest, str) else reported_cache_manifest
                if isinstance(parsed, list):
                    cm = parsed[:100]
                    total_b = 0
                    for it in cm:
                        if isinstance(it, dict):
                            try:
                                total_b += int(it.get('s') or 0)
                            except (TypeError, ValueError):
                                pass
                    row.cache_manifest_json = json.dumps(cm)
                    row.cache_manifest_total_bytes = total_b
                    row.cache_manifest_file_count = len(cm)
                else:
                    row.cache_manifest_json = json.dumps([])
                    row.cache_manifest_total_bytes = 0
                    row.cache_manifest_file_count = 0
                row.cache_manifest_updated_at = now_iso
            except Exception:
                row.cache_manifest_json = json.dumps([])
                row.cache_manifest_total_bytes = 0
                row.cache_manifest_file_count = 0
                row.cache_manifest_updated_at = now_iso

        if reported_download_progress is not None:
            try:
                import json as _json
                parsed_dp = _json.loads(reported_download_progress) if isinstance(reported_download_progress, str) else reported_download_progress
                if isinstance(parsed_dp, dict):
                    row.download_progress_json = json.dumps({
                        'filename': str(parsed_dp.get('filename') or '')[:260],
                        'name': str(parsed_dp.get('name') or '')[:260],
                        'bytes_read': int(parsed_dp.get('bytes_read') or 0),
                        'total_bytes': int(parsed_dp.get('total_bytes') or 0),
                        'percent': max(0.0, min(100.0, float(parsed_dp.get('percent') or 0.0))),
                        'status': str(parsed_dp.get('status') or 'downloading')[:40],
                        'updated_at_ms': int(parsed_dp.get('updated_at_ms') or 0),
                        'server_updated_at': now.isoformat(),
                    })
                else:
                    row.download_progress_json = None
            except Exception:
                row.download_progress_json = None

        db.session.commit()
        result = device_row_to_dict(row)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        raise

    if is_new_device:
        log_activity('device_connected', {'device_id': device_id, 'name': device_name}, user_id)
    return result


def get_connected_devices(user_id=None):
    """Get list of online devices for tenant (within DEVICE_TIMEOUT)"""
    all_list = get_all_devices_with_status(user_id)
    return [d for d in all_list if d.get('online')]


def get_all_devices_with_status(user_id=None):
    """Get all devices for tenant with online/offline status (TenantDisplay is source of truth)."""
    if user_id is None:
        user_id = current_user.id

    _import_legacy_devices_json_if_needed(user_id)
    now = datetime.now()
    result = []
    from models import TenantDisplay
    for reg in TenantDisplay.query.filter_by(user_id=user_id).all():
        device_data = device_row_to_dict(reg)
        _append_device_status_row(result, user_id, reg.device_id, device_data, now)
    result.sort(key=lambda x: (len(str(x.get('id', ''))), str(x.get('id', ''))))
    return result


def get_device_count(user_id=None):
    """Get total number of devices for tenant"""
    if user_id is None:
        user_id = current_user.id
    return len(get_all_devices_with_status(user_id))


def get_total_devices_all_users():
    """Get total device count across all tenants (for admin)"""
    from models import User
    total = 0
    for user in User.query.all():
        total += get_device_count(user.id)
    return total


def get_total_storage_all_users():
    """Get total storage used across all tenants in GB (for admin)"""
    from models import User
    total = 0.0
    for user in User.query.all():
        total += get_storage_usage(user.id)
    return round(total, 2)


def load_admin_settings():
    """Load admin settings from JSON file"""
    path = os.path.join(Config.UPLOAD_FOLDER, '..', 'admin_settings.json')
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return {
            'site_name': 'Digital Signage',
            'support_email': '',
            'default_trial_days': 7,
            'maintenance_mode': False,
            'payoneer_email': '',
            'payoneer_instructions': '',
        }
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        data.setdefault('payoneer_email', '')
        data.setdefault('payoneer_instructions', '')
        return data
    except Exception:
        return {'site_name': 'Digital Signage', 'support_email': '', 'default_trial_days': 7, 'maintenance_mode': False, 'payoneer_email': '', 'payoneer_instructions': ''}


def save_admin_settings(settings):
    """Save admin settings to JSON file"""
    data_dir = os.path.join(Config.UPLOAD_FOLDER, '..')
    data_dir = os.path.normpath(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, 'admin_settings.json')
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix='admin_settings.', suffix='.tmp', dir=data_dir, text=True)
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            tmp_fd = None
            json.dump(settings, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def tenant_displays_play_targets(user_id, target_all, device_ids, force_broadcast=False):
    """Return TenantDisplay rows for a play command. When target_all, skips devices with an active program unless force_broadcast."""
    from models import TenantDisplay
    _import_legacy_devices_json_if_needed(user_id)
    q = TenantDisplay.query.filter_by(user_id=user_id)
    if target_all:
        rows = list(q.all())
        if not force_broadcast:
            rows = [r for r in rows if not (r.active_program_id or '').strip()]
        return rows
    if not device_ids:
        return []
    return q.filter(TenantDisplay.device_id.in_(list(device_ids))).all()


def play_video_to_devices(filename, device_ids, user_id):
    """Play video on specified devices for user (DB-backed)."""
    from models import TenantDisplay, db
    _import_legacy_devices_json_if_needed(user_id)
    q = TenantDisplay.query.filter_by(user_id=user_id)
    rows = q.filter(TenantDisplay.device_id.in_(device_ids)).all() if device_ids else q.all()
    for row in rows:
        row.current_video = filename
        row.command_id = new_playback_command_id()
        row.active_program_id = None
        row.playback_cache_only = False
        bump_playback_state_version(row)
    db.session.commit()
    log_activity('video_played', {
        'filename': filename,
        'device_count': len(rows),
    }, user_id)


def send_verification_email(to_email, username, verify_url):
    """Send email verification link. Returns True if sent, False if mail not configured or failed."""
    if not Config.MAIL_SERVER or not Config.MAIL_USERNAME or not Config.MAIL_PASSWORD:
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Verify your email - Digital Signage'
        msg['From'] = Config.MAIL_DEFAULT_SENDER or Config.MAIL_USERNAME
        msg['To'] = to_email
        text = f"Hi {username},\n\nPlease verify your email by opening this link:\n{verify_url}\n\nThis link expires in 24 hours.\n\n— Digital Signage"
        html = f"""<p>Hi {username},</p><p>Please verify your email by clicking the link below:</p><p><a href="{verify_url}">{verify_url}</a></p><p>This link expires in 24 hours.</p><p>— Digital Signage</p>"""
        msg.attach(MIMEText(text, 'plain'))
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT) as server:
            if Config.MAIL_USE_TLS:
                server.starttls()
            server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            server.sendmail(msg['From'], to_email, msg.as_string())
        return True
    except Exception:
        return False
