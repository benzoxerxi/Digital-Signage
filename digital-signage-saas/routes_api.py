"""
API Routes for Digital Signage Control
Multi-tenant API endpoints
"""
from flask import Blueprint, request, jsonify, send_file, Response, stream_with_context, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from config import Config
from datetime import datetime
import os
import json
import hashlib
import tempfile
from sqlalchemy import text

# Import helper functions from utils
from utils import (
    load_json_file, save_json_file, get_content_folder, get_data_file_path,
    allowed_file, get_connected_devices, get_all_devices_with_status,
    get_device_count, update_device_heartbeat, add_removed_device, log_activity, get_storage_usage, device_lock,
    set_current_video_display_name, get_current_video_display_name,
    delete_tenant_display_registry, sync_device_registry_row, merge_registry_into_devices_dict,
    new_playback_command_id, bump_playback_state_version, tenant_displays_play_targets,
    device_row_to_dict, normalize_command_id_for_api,
)
from models import TenantDisplay, db, User
from device_auth import issue_device_access_token, get_bearer_token, resolve_playback_user_id
import time
import threading

_CODE_ATTEMPT_LOCK = threading.Lock()
_CODE_ATTEMPTS_BY_IP = {}

api_bp = Blueprint('api', __name__)


def _merge_playback_request_params():
    """Merge query string with JSON body (POST). Body values override query for duplicate keys.

    Some proxies / Flask configs return None from get_json() even with a valid body; always
    parse raw POST data as JSON when possible.
    """
    merged = request.args.to_dict(flat=True)
    if request.method == 'POST':
        body = None
        raw = request.get_data(cache=True, as_text=True)
        if raw:
            raw = raw.strip()
            if raw.startswith('\ufeff'):
                raw = raw[1:]
        if raw:
            try:
                body = json.loads(raw)
            except Exception:
                body = None
        if not isinstance(body, dict):
            body = request.get_json(force=True, silent=True)
        if isinstance(body, dict):
            for k, v in body.items():
                if v is not None:
                    merged[k] = v
    return merged


def _cache_manifest_param_to_json_string(params):
    """Return JSON string for update_device_heartbeat, or None if client did not send a manifest."""
    if 'cache_manifest' not in params:
        return None
    cm = params.get('cache_manifest')
    if isinstance(cm, list):
        return json.dumps(cm)[:16000]
    if isinstance(cm, str):
        return (cm or '[]')[:16000]
    return None


def _download_progress_param_to_json_string(params):
    """Return compact JSON object string for per-device download progress, or None."""
    if 'download_progress' not in params:
        return None
    dp = params.get('download_progress')
    try:
        if isinstance(dp, str):
            dp = json.loads(dp)
        if not isinstance(dp, dict):
            return None
        compact = {
            'filename': str(dp.get('filename') or '')[:260],
            'name': str(dp.get('name') or '')[:260],
            'bytes_read': int(dp.get('bytes_read') or 0),
            'total_bytes': int(dp.get('total_bytes') or 0),
            'percent': float(dp.get('percent') or 0.0),
            'status': str(dp.get('status') or 'downloading')[:40],
            'updated_at_ms': int(dp.get('updated_at_ms') or 0),
        }
        return json.dumps(compact)
    except Exception:
        return None


def _compute_file_md5(filepath):
    md5 = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            md5.update(chunk)
    return md5.hexdigest()


def _log_api_error(endpoint, error, user_id=None, device_id=None):
    payload = {
        'endpoint': endpoint,
        'error': str(error),
        'user_id': user_id,
        'device_id': device_id,
        'ip': request.remote_addr,
    }
    print(json.dumps(payload, ensure_ascii=True))


def _rate_limit_connection_code(ip_key, max_per_minute=48):
    now = time.time()
    with _CODE_ATTEMPT_LOCK:
        bucket = _CODE_ATTEMPTS_BY_IP.setdefault(ip_key, [])
        bucket[:] = [t for t in bucket if now - t < 60]
        if len(bucket) >= max_per_minute:
            return False
        bucket.append(now)
    return True


@api_bp.route('/auth/device-token', methods=['POST'])
def issue_device_token():
    """Exchange 9-digit connection code for a short-lived JWT (use Authorization: Bearer on playback APIs)."""
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or data.get('connection_code') or '').strip()
    if not code or len(code) != 9 or not code.isdigit():
        return jsonify({'success': False, 'error': 'Valid 9-digit code is required'}), 400
    if not _rate_limit_connection_code('token:' + (request.remote_addr or 'x')):
        return jsonify({'success': False, 'error': 'Too many requests'}), 429
    user = User.get_by_connection_code(code)
    if not user or not user.is_active:
        return jsonify({'success': False, 'error': 'Invalid code'}), 403
    if not user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription inactive'}), 403
    ttl = int(current_app.config.get('DEVICE_JWT_TTL_SECONDS', 86400))
    token = issue_device_access_token(user.id, ttl_seconds=ttl)
    return jsonify({
        'success': True,
        'access_token': token,
        'token_type': 'Bearer',
        'expires_in': ttl,
    })



@api_bp.route('/devices/verify', methods=['POST'])
def verify_device_connection():
    """Lightweight setup-time validation for 9-digit code + account state."""
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or data.get('connection_code') or '').strip()
    if not code or len(code) != 9 or not code.isdigit():
        return jsonify({'success': False, 'error': 'Valid 9-digit code is required'}), 400
    if not _rate_limit_connection_code('verify:' + (request.remote_addr or 'x')):
        return jsonify({'success': False, 'error': 'Too many requests'}), 429

    user = User.get_by_connection_code(code)
    if not user or not user.is_active:
        return jsonify({'success': False, 'error': 'Invalid code'}), 403
    if not user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription inactive'}), 403

    return jsonify({
        'success': True,
        'user_id': user.id,
        'device_id': data.get('device_id'),
        'device_name': data.get('device_name'),
    })


def _ensure_video_metadata(video, content_folder):
    """Populate hash/size once and persist in playlist instead of hashing every request."""
    if video.get('drive_file_id'):
        return False
    filename = video.get('filename')
    if not filename:
        return False
    filepath = os.path.join(content_folder, filename) if content_folder else None
    if not filepath or not os.path.exists(filepath):
        return False
    changed = False
    stat = os.stat(filepath)
    size_bytes = int(stat.st_size)
    size_text = f"{size_bytes / (1024 * 1024):.1f} MB"
    if int(video.get('size_bytes', -1)) != size_bytes:
        video['size_bytes'] = size_bytes
        video['size'] = size_text
        changed = True
    elif not video.get('size'):
        video['size'] = size_text
        changed = True
    if not video.get('hash'):
        video['hash'] = _compute_file_md5(filepath)
        changed = True
    return changed


# ============================================================================
# PLAYLIST & VIDEO MANAGEMENT
# ============================================================================

@api_bp.route('/playlist')
def get_playlist():
    """Get current playlist - for web (login) or APK (9-digit code)"""
    from models import User
    user_id = None

    # APK: resolve user by 9-digit connection code
    code_param = request.args.get('code')
    if code_param:
        user = User.get_by_connection_code(code_param)
        if not user:
            return jsonify({'error': 'Invalid connection code'}), 404
        if not user.is_active or not user.is_subscription_active():
            return jsonify({'error': 'Account inactive or subscription expired'}), 403
        user_id = user.id
    elif current_user.is_authenticated:
        user_id = current_user.id
    else:
        return jsonify({'error': 'Provide ?code= (9-digit) or log in'}), 401

    playlist = load_json_file('playlist.json', {'videos': [], 'settings': {'interval': 30, 'loop': True}}, user_id)
    base_url = request.url_root.rstrip('/')
    code_suffix = f'?code={code_param}' if code_param else ''
    content_folder = get_content_folder(user_id)
    metadata_changed = False
    for video in playlist.get('videos', []):
        if video.get('drive_file_id'):
            # Google Drive item: APK uses "drive:ID" as stable id, url for download
            video['filename'] = f"drive:{video['drive_file_id']}"
            video['url'] = f"{base_url}/api/video/drive/{video['drive_file_id']}{code_suffix}"
            if not video.get('name'):
                video['name'] = video.get('title', video['drive_file_id'])
        else:
            # Server file
            if content_folder and _ensure_video_metadata(video, content_folder):
                metadata_changed = True
            if 'url' not in video or not str(video.get('url', '')).startswith('http'):
                video['url'] = f"{base_url}/api/video/{video['filename']}{code_suffix}"
                metadata_changed = True

    if metadata_changed:
        save_json_file('playlist.json', playlist, user_id)

    return jsonify(playlist)




# ============================================================================
# DEVICE LAYOUT (APK can request layout; no program feature – return program: null)
# ============================================================================


def _resolve_program_payload_for_device(user, device_id, code_param=None):
    """Return active layout program payload for a device, or None."""
    row = TenantDisplay.query.filter_by(user_id=user.id, device_id=device_id).first()
    active_prog_id = row.active_program_id if row else None
    if not active_prog_id:
        return None

    programs = load_json_file('programs.json', {'programs': []}, user.id)
    prog = next((p for p in programs['programs'] if p['id'] == active_prog_id), None)
    if not prog:
        return None

    code_suffix = f'?code={code_param}' if code_param else ''
    base_url = request.host_url.rstrip('/')

    elements_out = []
    for el in prog.get('elements', []):
        src = el.get('src', '') or ''
        el_type = el.get('type', 'video')

        if el_type in ('video', 'image'):
            if not src:
                continue
            if src.startswith('drive:'):
                url = f'{base_url}/api/video/{src}{code_suffix}'
            elif src.startswith('http'):
                url = src
            else:
                url = f'{base_url}/api/video/{src}{code_suffix}'
            props = {'url': url}
        elif el_type == 'text':
            props = {'content': el.get('name', ''), 'fontSize': 24, 'color': '#FFFFFF', 'alignment': 'left'}
        elif el_type == 'webview':
            if not src:
                continue
            props = {'url': src}
        else:
            continue

        elements_out.append({
            'id': el.get('id'),
            'type': el_type,
            'x': el.get('x', 0),
            'y': el.get('y', 0),
            'width': el.get('width', 200),
            'height': el.get('height', 200),
            'zIndex': el.get('zIndex', 0),
            'props': props,
        })

    return {
        'id': prog['id'],
        'name': prog.get('name', ''),
        'width': prog.get('width', 1920),
        'height': prog.get('height', 1080),
        'elements': elements_out,
    }
@api_bp.route('/device_layout')
def get_device_layout():
    """Return active program layout for a device (polled by APK)."""
    user = None
    uid, err = resolve_playback_user_id()
    if err:
        return err
    if uid is not None:
        user = User.query.get(uid)
    code_param = request.args.get('code')
    if not user and code_param:
        user = User.get_by_connection_code(code_param)
    if not user:
        user_id_param = request.args.get('user_id')
        if user_id_param:
            try:
                user = User.query.get(int(user_id_param))
            except (TypeError, ValueError):
                user = None
    if not user:
        return jsonify({'error': 'User not found', 'message': 'Invalid connection code or user_id'}), 404
    if not user.is_active or not user.is_subscription_active():
        return jsonify({'error': 'Account inactive or subscription expired'}), 403
    device_id = request.args.get('device_id') or request.remote_addr.replace('.', '_')

    row = TenantDisplay.query.filter_by(user_id=user.id, device_id=device_id).first()
    active_prog_id = row.active_program_id if row else None

    if not active_prog_id:
        return jsonify({'deviceId': device_id, 'userId': user.id, 'program': None})

    programs = load_json_file('programs.json', {'programs': []}, user.id)
    prog = next((p for p in programs['programs'] if p['id'] == active_prog_id), None)
    if not prog:
        return jsonify({'deviceId': device_id, 'userId': user.id, 'program': None})

    code_suffix = f'?code={code_param}' if code_param else ''
    base_url = request.host_url.rstrip('/')

    elements_out = []
    for el in prog.get('elements', []):
        src = el.get('src', '') or ''
        el_type = el.get('type', 'video')

        if el_type in ('video', 'image'):
            if not src:
                continue
            if src.startswith('drive:'):
                url = f'{base_url}/api/video/{src}{code_suffix}'
            elif src.startswith('http'):
                url = src
            else:
                url = f'{base_url}/api/video/{src}{code_suffix}'
            props = {'url': url}
        elif el_type == 'text':
            props = {'content': el.get('name', ''), 'fontSize': 24, 'color': '#FFFFFF', 'alignment': 'left'}
        elif el_type == 'webview':
            if not src:
                continue
            props = {'url': src}
        else:
            continue

        elements_out.append({
            'id': el.get('id'),
            'type': el_type,
            'x': el.get('x', 0),
            'y': el.get('y', 0),
            'width': el.get('width', 200),
            'height': el.get('height', 200),
            'zIndex': el.get('zIndex', 0),
            'props': props,
        })

    return jsonify({
        'deviceId': device_id,
        'userId': user.id,
        'program': {
            'id': prog['id'],
            'name': prog.get('name', ''),
            'width': prog.get('width', 1920),
            'height': prog.get('height', 1080),
            'elements': elements_out,
        }
    })


@api_bp.route('/playback/play-program', methods=['POST'])
@login_required
def play_program():
    """Assign a saved program layout to selected devices."""
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403

    data = request.json or {}
    program_id = data.get('program_id')
    device_ids = data.get('device_ids') or []
    target_all = bool(data.get('target_all'))

    if not program_id:
        return jsonify({'success': False, 'error': 'program_id is required'}), 400

    programs = load_json_file('programs.json', {'programs': []})
    prog = next((p for p in programs['programs'] if p['id'] == program_id), None)
    if not prog:
        return jsonify({'success': False, 'error': 'Program not found'}), 404

    if not target_all and not device_ids:
        return jsonify({'success': False, 'error': 'Select at least one display or set target_all'}), 400

    from flask_login import current_user as _cu
    merge_registry_into_devices_dict(_cu.id, {})
    updated = 0
    if target_all:
        rows = TenantDisplay.query.filter_by(user_id=_cu.id).all()
    else:
        rows = TenantDisplay.query.filter_by(user_id=_cu.id).filter(
            TenantDisplay.device_id.in_(list(device_ids))
        ).all()
    for row in rows:
        row.active_program_id = program_id
        row.current_video = None
        row.command_id = new_playback_command_id()
        row.current_video_display_name = None
        row.playback_cache_only = False
        bump_playback_state_version(row)
        updated += 1
    db.session.commit()
    log_activity('program_played', {'program_id': program_id, 'device_count': updated, 'target_all': target_all})

    return jsonify({
        'success': True,
        'program_id': program_id,
        'program_name': prog.get('name', ''),
        'devices_updated': updated,
        'target': 'all' if target_all else 'selected',
    })


@api_bp.route('/upload', methods=['POST'])
@login_required
def upload_video():
    """Upload a new video file"""
    try:
        # Check subscription
        if not current_user.is_subscription_active():
            return jsonify({'success': False, 'error': 'Subscription expired'}), 403
        
        # Check storage limit
        current_storage = get_storage_usage()
        limits = current_user.get_plan_limits()
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400
        
        # Check if adding this file would exceed storage limit
        # Estimate file size (this is approximate)
        file.seek(0, os.SEEK_END)
        file_size_gb = file.tell() / (1024 ** 3)
        file.seek(0)
        
        if not current_user.can_upload_content(current_storage + file_size_gb):
            return jsonify({
                'success': False,
                'error': f'Storage limit exceeded. Your plan allows {limits["max_storage_gb"]} GB.'
            }), 403
        
        filename = secure_filename(file.filename)
        content_folder = get_content_folder()
        
        # Ensure content folder exists
        if not content_folder:
            return jsonify({'success': False, 'error': 'Content folder error'}), 500
        
        os.makedirs(content_folder, exist_ok=True)
        filepath = os.path.join(content_folder, filename)
        
        # Save file
        file.save(filepath)
        stat = os.stat(filepath)
        size_bytes = int(stat.st_size)
        size_text = f"{size_bytes / (1024 * 1024):.1f} MB"
        file_hash = _compute_file_md5(filepath)
        
        # Update playlist
        playlist = load_json_file('playlist.json', {'videos': [], 'settings': {'interval': 30, 'loop': True}})
        
        if not any(v['filename'] == filename for v in playlist.get('videos', [])):
            playlist['videos'].append({
                'filename': filename,
                'name': filename,
                'added': datetime.now().isoformat(),
                'url': f'/api/video/{filename}',
                'size': size_text,
                'size_bytes': size_bytes,
                'hash': file_hash,
            })
            save_json_file('playlist.json', playlist)
            log_activity('video_uploaded', {'filename': filename})
        
        return jsonify({'success': True, 'filename': filename})
    
    except Exception as e:
        _log_api_error('/api/upload', e, user_id=current_user.id if current_user.is_authenticated else None)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/video/drive/<file_id>')
def get_drive_video(file_id):
    """Stream a video from the user's Google Drive (proxy). Auth: ?code= (APK) or session."""
    from flask import Response
    from routes_google_drive import stream_drive_file
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    if not user_id:
        code_param = request.args.get('code')
        if code_param:
            from models import User
            user = User.get_by_connection_code(code_param)
            if user and user.is_active and user.is_subscription_active():
                user_id = user.id
        if not user_id:
            user_id_param = request.args.get('user_id')
            if user_id_param:
                try:
                    from models import User
                    user = User.query.get(int(user_id_param))
                    if user and user.is_active:
                        user_id = user.id
                except (ValueError, TypeError):
                    pass
    if not user_id:
        return jsonify({'error': 'Invalid code or user_id'}), 400
    try:
        def generate():
            for chunk in stream_drive_file(user_id, file_id):
                yield chunk
        return Response(
            generate(),
            mimetype='video/mp4',
            headers={'Accept-Ranges': 'bytes'},
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        return jsonify({'error': 'Drive error', 'message': str(e)}), 500


@api_bp.route('/video/<filename>')
def get_video(filename):
    """Serve video file - supports authenticated users, code, or user_id parameter"""
    # Check if authenticated via session
    if current_user.is_authenticated:
        content_folder = get_content_folder()
        filepath = os.path.join(content_folder, secure_filename(filename))
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'Video not found'}), 404
        
        import mimetypes
        return send_file(filepath, mimetype=mimetypes.guess_type(filepath)[0])
    
    # For Android APK - Support code (9-digit) or user_id (legacy)
    from models import User
    user = None
    code_param = request.args.get('code')
    if code_param:
        user = User.get_by_connection_code(code_param)
    if not user:
        user_id_param = request.args.get('user_id')
        if user_id_param:
            try:
                user = User.query.get(int(user_id_param))
            except (ValueError, TypeError):
                pass
    if not user:
        return jsonify({'error': 'Invalid code or user_id. Use your 9-digit connection code.'}), 400
    
    user_id = user.id
    content_folder = get_content_folder(user_id)
    if not content_folder:
        return jsonify({'error': 'Invalid user'}), 404
        
    filepath = os.path.join(content_folder, secure_filename(filename))
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'Video not found'}), 404
    
    import mimetypes
    return send_file(filepath, mimetype=mimetypes.guess_type(filepath)[0])


@api_bp.route('/video/<filename>', methods=['DELETE'])
@login_required
def delete_video(filename):
    """Delete a video file"""
    content_folder = get_content_folder()
    filepath = os.path.join(content_folder, secure_filename(filename))
    
    if os.path.exists(filepath):
        os.remove(filepath)
    
    # Remove from playlist
    playlist = load_json_file('playlist.json', {'videos': [], 'settings': {'interval': 30, 'loop': True}})
    playlist['videos'] = [v for v in playlist.get('videos', []) if v['filename'] != filename]
    save_json_file('playlist.json', playlist)
    
    log_activity('video_deleted', {'filename': filename})
    
    return jsonify({'success': True})


# ============================================================================
# PLAYBACK CONTROL
# ============================================================================

@api_bp.route('/playback/state', methods=['GET', 'POST'])
def get_playback_state():
    """Get current playback state - Displays poll this endpoint"""
    params = _merge_playback_request_params()

    device_id = params.get('device_id')
    if not device_id:
        # If no device_id, use IP address as device identifier
        device_id = request.remote_addr.replace('.', '_')

    device_name = params.get('device_name')

    # Check if user is authenticated via session
    if current_user.is_authenticated:
        device_info = {
            'user_agent': request.headers.get('User-Agent', ''),
            'ip': request.remote_addr
        }

        device_data = update_device_heartbeat(device_id, device_name, device_info)

        # Load playlist settings
        playlist = load_json_file('playlist.json', {
            'videos': [],
            'settings': {'interval': 30, 'loop': True},
            'active_playlist_id': None
        })

        if device_data.get('current_video'):
            response = {
                'current_video': device_data['current_video'],
                'command_id': normalize_command_id_for_api(device_data.get('command_id')),
                'mode': 'auto' if len(playlist.get('videos', [])) > 1 else 'manual',
                'last_update': device_data.get('last_seen'),
                'loop': playlist.get('settings', {}).get('loop', True),
                'interval': playlist.get('settings', {}).get('interval', 30)
            }

            # If there's an active playlist with multiple videos, include the playlist
            if len(playlist.get('videos', [])) > 1:
                response['playlist'] = {
                    'videos': [v['filename'] for v in playlist['videos']],
                    'current_index': next((i for i, v in enumerate(playlist['videos'])
                                          if v['filename'] == device_data['current_video']), 0)
                }

            return jsonify(response)
        else:
            return jsonify({
                'current_video': None,
                'command_id': '',
                'mode': 'manual',
                'last_update': datetime.now().isoformat(),
                'loop': True
            })

    # Android: Bearer device JWT (preferred) or 9-digit code / legacy user_id
    user = None
    uid, err = resolve_playback_user_id()
    if err:
        return err
    if uid is not None:
        user = User.query.get(uid)
    connection_code = params.get('code')
    if not user and connection_code:
        if not _rate_limit_connection_code('hb:' + (request.remote_addr or 'x')):
            return jsonify({
                'error': 'Too many requests',
                'message': 'Use POST /api/auth/device-token then Authorization: Bearer on this endpoint.',
            }), 429
        user = User.get_by_connection_code(connection_code)
    if not user:
        user_id_param = params.get('user_id')
        if user_id_param:
            try:
                uid_legacy = int(user_id_param)
                user = User.query.get(uid_legacy)
            except (ValueError, TypeError):
                pass

    # Verify user exists and is active
    try:
        if not user:
            return jsonify({
                'error': 'User not found',
                'message': 'Invalid connection code or user_id. Check your 9-digit code in Account settings.'
            }), 404

        if not user.is_active:
            return jsonify({
                'error': 'User inactive',
                'message': 'Account has been deactivated'
            }), 404

        if not user.is_subscription_active():
            return jsonify({
                'error': 'Subscription expired',
                'message': f'Subscription is not active. Current status: {user.subscription_status}'
            }), 403
    except Exception as e:
        _log_api_error('/api/playback/state.verify-user', e, user_id=user.id if user else None, device_id=device_id)
        return jsonify({
            'error': 'Database error',
            'message': str(e)
        }), 500

    user_id = user.id
    fs = params.get('from_setup')
    from_setup = fs is True or str(fs) == '1'
    reported_current_video = params.get('current_video')  # from device cache (APK sends in heartbeat)
    reported_current_video_name = params.get('current_video_name')  # display name from device (e.g. Drive file name)
    device_info = {
        'user_agent': request.headers.get('User-Agent', ''),
        'ip': request.remote_addr
    }
    hb_kwargs = dict(
        reported_current_video=reported_current_video,
        reported_current_video_name=reported_current_video_name,
    )
    cm_json = _cache_manifest_param_to_json_string(params)
    if cm_json is not None:
        hb_kwargs['reported_cache_manifest'] = cm_json
    dp_json = _download_progress_param_to_json_string(params)
    if dp_json is not None:
        hb_kwargs['reported_download_progress'] = dp_json

    try:
        device_data = update_device_heartbeat(
            device_id, device_name, device_info, user_id, from_setup=from_setup, **hb_kwargs
        )
        if device_data is None:
            return jsonify({
                'removed': True,
                'message': 'Device was removed from the control panel. Reconnect from setup.'
            }), 200

        # One-shot explicit play command: once device reports it is already on this video,
        # clear current_video so subsequent heartbeats return to normal playlist flow.
        server_current_video = device_data.get('current_video')
        if server_current_video and reported_current_video and reported_current_video == server_current_video:
            row = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
            if row and row.current_video == server_current_video:
                row.current_video = None
                row.current_video_display_name = None
                bump_playback_state_version(row)
                db.session.commit()
                set_current_video_display_name(user_id, device_id, None)
                device_data = device_row_to_dict(row)

        # Load playlist settings
        playlist = load_json_file('playlist.json', {
            'videos': [],
            'settings': {'interval': 30, 'loop': True},
            'active_playlist_id': None
        }, user_id)

        # Prefer code param for video URL (cleaner for APK)
        video_param = f'code={user.connection_code}' if user.connection_code else f'user_id={user_id}'
        program_payload = _resolve_program_payload_for_device(user, device_id, code_param=connection_code)
        # Include screenshot_requested and device_name so display can respond
        screenshot_requested = device_data.get('screenshot_requested', False)
        device_name_from_server = device_data.get('name')
        # If format was requested, include clear_cache and clear the flag after sending once
        clear_cache = device_data.get('clear_cache', False)
        if clear_cache:
            row_cc = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
            if row_cc and row_cc.clear_cache:
                row_cc.clear_cache = False
                bump_playback_state_version(row_cc)
                db.session.commit()

        pending_deletes = list(device_data.get('cache_delete_keys') or [])
        if pending_deletes:
            row_del = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
            if row_del:
                row_del.cache_delete_keys_json = json.dumps([])
                bump_playback_state_version(row_del)
                db.session.commit()
        if device_data.get('current_video'):
            # Only send the single commanded video; do not push playlist to device
            cv = device_data['current_video']
            if cv and cv.startswith('drive:'):
                _id = cv.split(':', 1)[1]
                video_url = f'/api/video/drive/{_id}?{video_param}'
            else:
                video_url = f'/api/video/{cv}?{video_param}' if cv else None
            current_video_name = get_current_video_display_name(user_id, device_id)
            response = {
                'current_video': cv,
                'command_id': normalize_command_id_for_api(device_data.get('command_id')),
                'mode': 'manual',
                'last_update': device_data.get('last_seen'),
                'video_url': video_url,
                'device_id': device_id,
                'loop': playlist.get('settings', {}).get('loop', True),
                'interval': playlist.get('settings', {}).get('interval', 30),
                'screenshot_requested': screenshot_requested,
                'device_name': device_name_from_server,
                'clear_cache': clear_cache,
                'playback_cache_only': bool(device_data.get('playback_cache_only')),
                'post_command_behavior': 'stop',
                'program': program_payload,
            }
            if current_video_name:
                response['current_video_name'] = current_video_name
            if pending_deletes:
                response['cache_delete_keys'] = pending_deletes
            return jsonify(response)
        else:
            idle_response = {
                'current_video': None,
                'command_id': normalize_command_id_for_api(device_data.get('command_id')),
                'mode': 'manual',
                'last_update': device_data.get('last_seen', datetime.now().isoformat()),
                'device_id': device_id,
                'status': 'connected',
                'loop': True,
                'screenshot_requested': screenshot_requested,
                'device_name': device_name_from_server,
                'clear_cache': clear_cache,
                'playback_cache_only': bool(device_data.get('playback_cache_only')),
                'post_command_behavior': 'resume_playlist',
                'program': program_payload,
            }
            if pending_deletes:
                idle_response['cache_delete_keys'] = pending_deletes
            return jsonify(idle_response)
    except Exception as e:
        _log_api_error('/api/playback/state', e, user_id=user_id, device_id=device_id)
        return jsonify({
            'error': 'Server error',
            'message': str(e)
        }), 500


@api_bp.route('/playback/events')
def playback_events_stream():
    """Server-Sent Events for playback state changes. Requires Authorization: Bearer (device JWT from POST /api/auth/device-token)."""
    uid, err = resolve_playback_user_id()
    if err:
        return err
    if uid is None:
        return jsonify({
            'error': 'Unauthorized',
            'message': 'Bearer device token required. Exchange your code at POST /api/auth/device-token',
        }), 401
    device_id = request.args.get('device_id') or request.remote_addr.replace('.', '_')
    app = current_app._get_current_object()

    def event_stream():
        last_sig = None
        while True:
            with app.app_context():
                try:
                    row = TenantDisplay.query.filter_by(user_id=uid, device_id=device_id).first()
                    if not row:
                        yield 'data: ' + json.dumps({'error': 'device_not_found'}) + '\n\n'
                        break
                    sig = (
                        row.state_version,
                        normalize_command_id_for_api(row.command_id),
                        row.current_video,
                        bool(row.clear_cache),
                        bool(row.screenshot_requested),
                        row.cache_delete_keys_json or '',
                    )
                    if sig != last_sig:
                        last_sig = sig
                        payload = {
                            'state_version': int(row.state_version or 0),
                            'command_id': normalize_command_id_for_api(row.command_id),
                            'current_video': row.current_video,
                            'clear_cache': bool(row.clear_cache),
                            'screenshot_requested': bool(row.screenshot_requested),
                            'playback_cache_only': bool(row.playback_cache_only),
                        }
                        yield 'data: ' + json.dumps(payload) + '\n\n'
                except Exception as ex:
                    yield 'data: ' + json.dumps({'error': str(ex)}) + '\n\n'
            time.sleep(0.35)

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


@api_bp.route('/playback/play', methods=['POST'])
@login_required
def play_video():
    """Play a specific video on selected devices. Accepts filename (server) or drive_file_id (Google Drive)."""
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    
    data = request.json or {}
    filename = data.get('filename')
    drive_file_id = data.get('drive_file_id')
    device_ids = data.get('device_ids')
    if device_ids is None:
        device_ids = []
    if not isinstance(device_ids, list):
        return jsonify({'success': False, 'error': 'device_ids must be a list'}), 400
    target_all = bool(data.get('target_all'))
    force_broadcast = bool(data.get('force_broadcast'))
    display_name = data.get('name', '').strip() or None  # e.g. "valentines tv 1.mp4" for Drive

    if drive_file_id:
        current_video_value = f'drive:{drive_file_id}'
    elif filename:
        current_video_value = filename
        content_folder = get_content_folder()
        filepath = os.path.join(content_folder, secure_filename(filename))
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Video not found'}), 404
    else:
        return jsonify({'success': False, 'error': 'No filename or drive_file_id provided'}), 400
    
    from flask_login import current_user as _cu
    updated_count = 0

    if not target_all and not device_ids:
        return jsonify({
            'success': False,
            'error': 'Select at least one display, or set target_all to true to play on all displays.'
        }), 400

    merge_registry_into_devices_dict(_cu.id, {})
    rows = tenant_displays_play_targets(_cu.id, target_all, device_ids, force_broadcast=force_broadcast)
    for row in rows:
        row.current_video = current_video_value
        row.command_id = new_playback_command_id()
        row.active_program_id = None
        row.playback_cache_only = False
        if display_name:
            row.current_video_display_name = display_name
        else:
            row.current_video_display_name = None
        set_current_video_display_name(_cu.id, row.device_id, display_name)
        bump_playback_state_version(row)
        updated_count += 1
    db.session.commit()
    log_activity('video_played', {'filename': current_video_value, 'device_count': updated_count, 'target_all': target_all})
    
    return jsonify({
        'success': True,
        'filename': current_video_value,
        'devices_updated': updated_count,
        'target': 'all' if target_all else 'selected'
    })


def _logical_video_from_cache_key(cache_key: str) -> str:
    """APK stores drive:fileId as drive_fileId on disk."""
    if cache_key.startswith('drive_'):
        return 'drive:' + cache_key[6:]
    return cache_key


@api_bp.route('/playback/play-cached', methods=['POST'])
@login_required
def play_cached_video():
    """Play a file that should already exist on the device's disk cache (no download)."""
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403

    data = request.json or {}
    cache_key = (data.get('cache_key') or '').strip()
    logical_video = (data.get('logical_video') or '').strip() or None
    display_name = (data.get('name') or '').strip() or None
    device_ids = data.get('device_ids')
    if device_ids is None:
        device_ids = []
    if not isinstance(device_ids, list):
        return jsonify({'success': False, 'error': 'device_ids must be a list'}), 400
    target_all = bool(data.get('target_all'))
    force_broadcast = bool(data.get('force_broadcast'))

    if not cache_key:
        return jsonify({'success': False, 'error': 'cache_key is required'}), 400

    if not logical_video:
        logical_video = _logical_video_from_cache_key(cache_key)

    from flask_login import current_user as _cu
    if not target_all and not device_ids:
        return jsonify({
            'success': False,
            'error': 'Select at least one display, or set target_all to true.',
        }), 400

    updated_count = 0
    merge_registry_into_devices_dict(_cu.id, {})
    rows = tenant_displays_play_targets(_cu.id, target_all, device_ids, force_broadcast=force_broadcast)
    for row in rows:
        row.current_video = logical_video
        row.command_id = new_playback_command_id()
        row.playback_cache_only = True
        row.active_program_id = None
        if display_name:
            row.current_video_display_name = display_name
        else:
            row.current_video_display_name = None
        set_current_video_display_name(_cu.id, row.device_id, display_name)
        bump_playback_state_version(row)
        updated_count += 1
    db.session.commit()
    log_activity('video_played_cache_only', {'cache_key': cache_key, 'logical': logical_video, 'device_count': updated_count})

    return jsonify({
        'success': True,
        'logical_video': logical_video,
        'cache_key': cache_key,
        'devices_updated': updated_count,
        'target': 'all' if target_all else 'selected',
    })


@api_bp.route('/playback/stop', methods=['POST'])
@login_required
def stop_playback():
    """Stop playback on all or selected devices"""
    data = request.json or {}
    device_ids = data.get('device_ids', [])
    
    from flask_login import current_user as _cu
    updated_count = 0
    merge_registry_into_devices_dict(_cu.id, {})
    if device_ids:
        rows = TenantDisplay.query.filter_by(user_id=_cu.id).filter(
            TenantDisplay.device_id.in_(list(device_ids))
        ).all()
    else:
        rows = TenantDisplay.query.filter_by(user_id=_cu.id).all()
    for row in rows:
        row.current_video = None
        row.status = 'idle'
        row.command_id = new_playback_command_id()
        row.current_video_display_name = None
        row.active_program_id = None
        row.playback_cache_only = False
        set_current_video_display_name(_cu.id, row.device_id, None)
        bump_playback_state_version(row)
        updated_count += 1
    db.session.commit()
    log_activity('playback_stopped', {'device_count': updated_count})
    
    return jsonify({
        'success': True,
        'devices_updated': updated_count,
        'target': 'selected' if device_ids else 'all'
    })


@api_bp.route('/playback/next', methods=['POST', 'GET'])
def next_video():
    """Called when device's current video ends. Server does not auto-send next video or playlist;
    only explicit Play from dashboard sends content. Return no next so device stops or shows screensaver."""
    user = None
    if current_user.is_authenticated:
        user = current_user
    if not user:
        uid, err = resolve_playback_user_id()
        if err:
            return err
        if uid is not None:
            user = User.query.get(uid)
    if not user:
        code_param = request.args.get('code')
        if code_param:
            user = User.get_by_connection_code(code_param)
    if not user:
        user_id_param = request.args.get('user_id')
        if user_id_param:
            try:
                user = User.query.get(int(user_id_param))
            except (ValueError, TypeError):
                pass
    if not user:
        return jsonify({'error': 'Invalid code or user_id'}), 400

    device_id = request.args.get('device_id') or request.remote_addr.replace('.', '_')

    # Do not auto-advance device to next video; do not register new devices with first video.
    # Only explicit Play from dashboard should set current_video on devices.
    return jsonify({
        'success': False,
        'error': 'No next video',
        'action': 'stop'
    }), 404


# ============================================================================
# DEVICE MANAGEMENT
# ============================================================================

@api_bp.route('/devices')
@login_required
def get_devices():
    """Get list of all devices (online and offline) for current user. Names are stored per device."""
    from flask_login import current_user as _cu
    devices = get_all_devices_with_status(_cu.id)
    connected_count = sum(1 for d in devices if d.get('online'))
    
    return jsonify({
        'devices': devices,
        'total': len(devices),
        'connected': connected_count
    })


@api_bp.route('/devices/<device_id>', methods=['PUT'])
@login_required
def update_device(device_id):
    """Update device information"""
    data = request.json
    from flask_login import current_user as _cu
    row = TenantDisplay.query.filter_by(user_id=_cu.id, device_id=device_id).first()
    if not row:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    if 'name' in data:
        row.display_name = (data['name'] or row.display_name)[:200]
    bump_playback_state_version(row)
    db.session.commit()
    d = device_row_to_dict(row)
    sync_device_registry_row(_cu.id, device_id, d)
    return jsonify({'success': True, 'device': d})


@api_bp.route('/devices/<device_id>/cache-delete', methods=['POST'])
@login_required
def queue_device_cache_delete(device_id):
    """Queue storage keys for the APK to delete from local disk on next heartbeat."""
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    data = request.json or {}
    keys = data.get('keys')
    if not isinstance(keys, list) or not keys:
        return jsonify({'success': False, 'error': 'keys (non-empty list) required'}), 400

    from flask_login import current_user as _cu
    row = TenantDisplay.query.filter_by(user_id=_cu.id, device_id=device_id).first()
    if not row:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    safe = []
    for k in keys:
        if not isinstance(k, str):
            continue
        k = k.strip()
        if not k or len(k) > 240:
            continue
        if any(bad in k for bad in ('..', '/', '\\')):
            continue
        safe.append(k)
    if not safe:
        return jsonify({'success': False, 'error': 'No valid keys'}), 400
    try:
        existing = json.loads(row.cache_delete_keys_json) if row.cache_delete_keys_json else []
    except Exception:
        existing = []
    if not isinstance(existing, list):
        existing = []
    merged = list(dict.fromkeys(existing + safe))[:80]
    row.cache_delete_keys_json = json.dumps(merged)
    bump_playback_state_version(row)
    db.session.commit()
    return jsonify({'success': True, 'queued': len(safe), 'pending_total': len(merged)})


@api_bp.route('/devices/<device_id>', methods=['DELETE'])
@login_required
def delete_device(device_id):
    """Remove a device from the panel. The APK will be told to return to setup on next heartbeat."""
    from flask_login import current_user as _cu
    row = TenantDisplay.query.filter_by(user_id=_cu.id, device_id=device_id).first()
    if row:
        db.session.delete(row)
        db.session.commit()
        log_activity('device_deleted', {'device_id': device_id})
    add_removed_device(_cu.id, device_id)
    delete_tenant_display_registry(_cu.id, device_id)
    
    return jsonify({'success': True})


@api_bp.route('/devices/<device_id>/screenshot/request', methods=['POST'])
@login_required
def request_device_screenshot(device_id):
    """Set flag so the display will capture and upload a screenshot on next poll"""
    from flask_login import current_user as _cu
    row = TenantDisplay.query.filter_by(user_id=_cu.id, device_id=device_id).first()
    if not row:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    row.screenshot_requested = True
    bump_playback_state_version(row)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Screenshot request sent to display'})


@api_bp.route('/devices/<device_id>/screenshot', methods=['GET'])
@login_required
def get_device_screenshot(device_id):
    """Return the latest screenshot for this device (if any)"""
    from flask_login import current_user as _cu
    row = TenantDisplay.query.filter_by(user_id=_cu.id, device_id=device_id).first()
    if not row:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    data_url = row.screenshot_data
    timestamp = row.screenshot_timestamp
    if not data_url:
        return jsonify({'success': False, 'screenshot': None})
    return jsonify({'success': True, 'screenshot': data_url, 'timestamp': timestamp})


@api_bp.route('/devices/<device_id>/screenshot/upload', methods=['POST'])
def upload_device_screenshot(device_id):
    """Accept screenshot from display (APK with ?code= or logged-in user)"""
    from models import User
    user_id = None
    code_param = request.args.get('code')
    if code_param:
        user = User.get_by_connection_code(code_param)
        if not user or not user.is_active:
            return jsonify({'success': False, 'error': 'Invalid code'}), 403
        user_id = user.id
    elif current_user.is_authenticated:
        user_id = current_user.id
    else:
        return jsonify({'success': False, 'error': 'Provide ?code= or log in'}), 401

    data = request.get_json(silent=True) or {}
    screenshot_b64 = data.get('screenshot')
    if not screenshot_b64:
        return jsonify({'success': False, 'error': 'No screenshot data'}), 400

    try:
        row = TenantDisplay.query.filter_by(user_id=user_id, device_id=device_id).first()
        if not row:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        row.screenshot_data = screenshot_b64
        row.screenshot_timestamp = datetime.now().isoformat()
        row.screenshot_requested = False
        bump_playback_state_version(row)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Screenshot received'})
    except Exception as e:
        _log_api_error('/api/devices/screenshot/upload', e, user_id=user_id, device_id=device_id)
        return jsonify({'success': False, 'error': 'Screenshot processing failed'}), 500


@api_bp.route('/devices/format', methods=['POST'])
@login_required
def format_devices():
    """Format/reset selected devices: stop playback, clear cache flag. Preserves device names."""
    data = request.json
    device_ids = data.get('device_ids', [])
    
    if not device_ids:
        return jsonify({'success': False, 'error': 'No devices specified'}), 400
    
    from flask_login import current_user as _cu
    formatted_count = 0
    for device_id in device_ids:
        row = TenantDisplay.query.filter_by(user_id=_cu.id, device_id=device_id).first()
        if not row:
            continue
        row.current_video = None
        row.status = 'idle'
        row.command_id = new_playback_command_id()
        row.clear_cache = True
        row.active_program_id = None
        row.playback_cache_only = False
        bump_playback_state_version(row)
        formatted_count += 1
        log_activity('device_formatted', {'device_id': device_id})
    db.session.commit()
    
    return jsonify({
        'success': True,
        'formatted_count': formatted_count
    })


# ============================================================================
# PLAYLISTS
# ============================================================================

@api_bp.route('/playlists', methods=['GET', 'POST'])
@login_required
def handle_playlists():
    """Get or create playlists (videos only)."""
    if request.method == 'GET':
        return jsonify(load_json_file('playlists.json', {'playlists': []}))
    
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    
    data = request.json or {}
    playlists = load_json_file('playlists.json', {'playlists': []})
    raw_videos = data.get('videos') or []
    # Normalize: allow strings (server filename) or objects { filename, name?, drive_file_id? }
    videos = []
    for v in raw_videos:
        if isinstance(v, dict):
            if v.get('drive_file_id'):
                videos.append({
                    'filename': f"drive:{v['drive_file_id']}",
                    'name': v.get('name') or v.get('drive_file_id'),
                    'drive_file_id': v['drive_file_id']
                })
            else:
                videos.append({
                    'filename': v.get('filename', ''),
                    'name': v.get('name') or v.get('filename', '')
                })
        else:
            fn = str(v)
            videos.append({'filename': fn, 'name': fn})
    
    import time
    new_playlist = {
        'id': f'playlist_{int(time.time())}',
        'name': data.get('name') or 'Untitled playlist',
        'videos': videos,
        'created': datetime.now().isoformat()
    }
    
    playlists['playlists'].append(new_playlist)
    save_json_file('playlists.json', playlists)
    log_activity('playlist_created', {'playlist_id': new_playlist['id']})
    
    return jsonify({'success': True, 'playlist': new_playlist})


@api_bp.route('/playlists/<playlist_id>', methods=['DELETE'])
@login_required
def delete_playlist(playlist_id):
    """Delete a playlist"""
    playlists = load_json_file('playlists.json', {'playlists': []})
    playlists['playlists'] = [p for p in playlists['playlists'] if p['id'] != playlist_id]
    save_json_file('playlists.json', playlists)
    log_activity('playlist_deleted', {'playlist_id': playlist_id})
    
    return jsonify({'success': True})


@api_bp.route('/playlists/<playlist_id>/activate', methods=['POST'])
@login_required
def activate_playlist(playlist_id):
    """Activate a playlist - copies it to the main playlist for playback"""
    try:
        # Load playlists
        playlists_data = load_json_file('playlists.json', {'playlists': []})
        
        # Find the playlist
        playlist = next((p for p in playlists_data['playlists'] if p['id'] == playlist_id), None)
        
        if not playlist:
            return jsonify({'success': False, 'error': 'Playlist not found'}), 404
        
        if not playlist.get('videos') or len(playlist['videos']) == 0:
            return jsonify({'success': False, 'error': 'Playlist is empty'}), 400
        
        user_id = current_user.id
        content_folder = get_content_folder(user_id)
        video_objects = []
        
        for video in playlist['videos']:
            if isinstance(video, dict) and video.get('drive_file_id'):
                # Google Drive entry
                video_objects.append({
                    'filename': f"drive:{video['drive_file_id']}",
                    'name': video.get('name') or video['drive_file_id'],
                    'drive_file_id': video['drive_file_id'],
                    'added': datetime.now().isoformat(),
                    'url': f"/api/video/drive/{video['drive_file_id']}"
                })
            else:
                # Server file (legacy string or object with filename)
                filename = video.get('filename', video) if isinstance(video, dict) else video
                filename = str(filename).strip()
                if not filename:
                    continue
                filepath = os.path.join(content_folder, filename) if content_folder else None
                if filepath and os.path.exists(filepath):
                    stat = os.stat(filepath)
                    video_objects.append({
                        'filename': filename,
                        'name': video.get('name', filename) if isinstance(video, dict) else filename,
                        'added': datetime.now().isoformat(),
                        'url': f'/api/video/{filename}',
                        'size': f"{stat.st_size / (1024*1024):.1f} MB"
                    })
        
        if len(video_objects) == 0:
            return jsonify({'success': False, 'error': 'No valid videos in playlist'}), 400
        
        main_playlist = load_json_file('playlist.json', {
            'videos': [],
            'settings': {'interval': 30, 'loop': True},
            'active_playlist_id': None,
            'active_playlist_name': None
        }, user_id)
        main_playlist['videos'] = video_objects
        main_playlist['active_playlist_id'] = playlist_id
        main_playlist['active_playlist_name'] = playlist['name']
        save_json_file('playlist.json', main_playlist, user_id)
        
        log_activity('playlist_activated', {
            'playlist_id': playlist_id,
            'playlist_name': playlist['name'],
            'video_count': len(video_objects)
        })
        
        return jsonify({
            'success': True,
            'playlist_name': playlist['name'],
            'video_count': len(video_objects),
            'videos': video_objects
        })
        
    except Exception as e:
        print(f"Playlist activation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# SCHEDULES
# ============================================================================

@api_bp.route('/schedules', methods=['GET', 'POST'])
@login_required
def handle_schedules():
    """Get or create schedules"""
    if request.method == 'GET':
        return jsonify(load_json_file('schedules.json', {'schedules': []}))
    
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    
    data = request.json
    schedules = load_json_file('schedules.json', {'schedules': []})
    
    import time
    new_schedule = {
        'id': f'schedule_{int(time.time())}',
        'time': data['time'],
        'days': data['days'],
        'content': data['content'],
        'device_ids': data.get('device_ids', []),
        'enabled': data.get('enabled', True),
        'created': datetime.now().isoformat()
    }
    
    schedules['schedules'].append(new_schedule)
    save_json_file('schedules.json', schedules)
    log_activity('schedule_created', {'schedule_id': new_schedule['id']})
    
    return jsonify({'success': True, 'schedule': new_schedule})


@api_bp.route('/schedules/<schedule_id>', methods=['DELETE'])
@login_required
def delete_schedule(schedule_id):
    """Delete a schedule"""
    schedules = load_json_file('schedules.json', {'schedules': []})
    schedules['schedules'] = [s for s in schedules['schedules'] if s['id'] != schedule_id]
    save_json_file('schedules.json', schedules)
    log_activity('schedule_deleted', {'schedule_id': schedule_id})
    
    return jsonify({'success': True})


# ============================================================================
# GROUPS
# ============================================================================

@api_bp.route('/groups', methods=['GET', 'POST'])
@login_required
def handle_groups():
    """Get or create device groups"""
    if request.method == 'GET':
        return jsonify(load_json_file('groups.json', {'groups': []}))
    
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    
    data = request.json
    groups = load_json_file('groups.json', {'groups': []})
    
    import time
    new_group = {
        'id': f'group_{int(time.time())}',
        'name': data['name'],
        'device_ids': data['device_ids'],
        'created': datetime.now().isoformat()
    }
    
    groups['groups'].append(new_group)
    save_json_file('groups.json', groups)
    log_activity('group_created', {'group_id': new_group['id']})
    
    return jsonify({'success': True, 'group': new_group})


@api_bp.route('/groups/<group_id>', methods=['DELETE'])
@login_required
def delete_group(group_id):
    """Delete a device group"""
    groups = load_json_file('groups.json', {'groups': []})
    groups['groups'] = [g for g in groups['groups'] if g['id'] != group_id]
    save_json_file('groups.json', groups)
    log_activity('group_deleted', {'group_id': group_id})
    
    return jsonify({'success': True})


# ============================================================================
# PROGRAMS (multi-zone layouts with drag-and-drop editor)
# ============================================================================

@api_bp.route('/programs', methods=['GET'])
@login_required
def get_programs():
    data = load_json_file('programs.json', {'programs': []})
    return jsonify(data)


@api_bp.route('/programs', methods=['POST'])
@login_required
def create_program():
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    data = request.json or {}
    name = (data.get('name') or '').strip()
    width = int(data.get('width', 1920))
    height = int(data.get('height', 1080))
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400
    width = max(320, min(7680, width))
    height = max(240, min(4320, height))
    import time
    program = {
        'id': f'prog_{int(time.time()*1000)}',
        'name': name,
        'width': width,
        'height': height,
        'elements': [],
        'created': datetime.now().isoformat(),
    }
    programs = load_json_file('programs.json', {'programs': []})
    programs['programs'].append(program)
    save_json_file('programs.json', programs)
    log_activity('program_created', {'program_id': program['id'], 'name': name})
    return jsonify({'success': True, 'program': program})


@api_bp.route('/programs/<program_id>', methods=['GET'])
@login_required
def get_program(program_id):
    programs = load_json_file('programs.json', {'programs': []})
    prog = next((p for p in programs['programs'] if p['id'] == program_id), None)
    if not prog:
        return jsonify({'error': 'Program not found'}), 404
    return jsonify(prog)


@api_bp.route('/programs/<program_id>', methods=['PUT'])
@login_required
def update_program(program_id):
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    programs = load_json_file('programs.json', {'programs': []})
    prog = next((p for p in programs['programs'] if p['id'] == program_id), None)
    if not prog:
        return jsonify({'success': False, 'error': 'Program not found'}), 404
    data = request.json or {}
    if 'name' in data:
        prog['name'] = (data['name'] or '').strip() or prog['name']
    if 'elements' in data:
        elements = []
        for i, el in enumerate(data['elements']):
            elements.append({
                'id': el.get('id') or f'el_{i}',
                'type': el.get('type', 'video'),
                'src': el.get('src', ''),
                'name': el.get('name', ''),
                'x': float(el.get('x', 0)),
                'y': float(el.get('y', 0)),
                'width': float(el.get('width', 200)),
                'height': float(el.get('height', 200)),
                'zIndex': int(el.get('zIndex', i)),
            })
        prog['elements'] = elements
    save_json_file('programs.json', programs)
    log_activity('program_updated', {'program_id': program_id})
    return jsonify({'success': True, 'program': prog})


@api_bp.route('/programs/<program_id>', methods=['DELETE'])
@login_required
def delete_program(program_id):
    programs = load_json_file('programs.json', {'programs': []})
    programs['programs'] = [p for p in programs['programs'] if p['id'] != program_id]
    save_json_file('programs.json', programs)
    log_activity('program_deleted', {'program_id': program_id})
    return jsonify({'success': True})


# ============================================================================
# ANALYTICS
# ============================================================================

@api_bp.route('/analytics')
@login_required
def get_analytics():
    """Get analytics data for current user"""
    from models import ActivityLog

    # Get recent activities from database
    activities = ActivityLog.query.filter_by(user_id=current_user.id)\
        .order_by(ActivityLog.created_at.desc()).limit(100).all()

    events = [{
        'timestamp': a.created_at.isoformat(),
        'type': a.event_type,
        'data': json.loads(a.event_data) if a.event_data else {}
    } for a in activities]

    # Real stats for current user (tenant)
    storage_gb = round(get_storage_usage(), 2)
    total_devices = get_device_count()
    connected = get_connected_devices()
    active_now = len(connected)
    total_plays = len([e for e in events if e['type'] == 'video_played'])

    # Avg uptime: % of registered devices that are currently online (or 100% if no devices)
    avg_uptime_percent = round((active_now / total_devices * 100) if total_devices else 100, 0)

    stats = {
        'total_plays': total_plays,
        'total_uploads': len([e for e in events if e['type'] == 'video_uploaded']),
        'storage_used_gb': storage_gb,
        'content_size_gb': storage_gb,
        'device_count': total_devices,
        'active_devices': active_now,
        'avg_uptime_percent': int(avg_uptime_percent),
    }

    return jsonify({
        'stats': stats,
        'events': events
    })


@api_bp.route('/status')
def get_status():
    """Readiness status: includes DB and lightweight disk write checks."""
    from models import db
    checks = {'db_read': False, 'db_write': False, 'disk_rw': False}
    errors = []
    try:
        db.session.execute(text("SELECT 1"))
        checks['db_read'] = True
        db.session.execute(text("CREATE TEMP TABLE IF NOT EXISTS healthcheck_tmp (v INTEGER)"))
        db.session.execute(text("INSERT INTO healthcheck_tmp (v) VALUES (1)"))
        db.session.execute(text("DELETE FROM healthcheck_tmp"))
        checks['db_write'] = True
        db.session.commit()
    except Exception as e:
        errors.append(f"db: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass

    try:
        base_dir = os.path.dirname(get_data_file_path('healthcheck.tmp', current_user.id if current_user.is_authenticated else 1) or '.')
        os.makedirs(base_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix='healthcheck.', suffix='.tmp', dir=base_dir, text=True)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(datetime.utcnow().isoformat())
            f.flush()
            os.fsync(f.fileno())
        os.remove(tmp_path)
        checks['disk_rw'] = True
    except Exception as e:
        errors.append(f"disk_rw: {e}")

    ready = all(checks.values())
    payload = {
        'online': ready,
        'ready': ready,
        'checks': checks,
        'server_time': datetime.now().isoformat(),
    }
    if errors:
        payload['errors'] = errors
    if current_user.is_authenticated:
        playlist = load_json_file('playlist.json', {'videos': [], 'settings': {'interval': 30, 'loop': True}})
        payload.update({
            'video_count': len(playlist.get('videos', [])),
            'connected_devices': len(get_connected_devices()),
            'subscription_active': current_user.is_subscription_active(),
            'plan': current_user.plan,
        })
    else:
        payload['message'] = 'Server is running' if ready else 'Server not ready'
    return jsonify(payload), (200 if ready else 503)


# Simple test endpoint for Android APK debugging
@api_bp.route('/test', methods=['GET', 'POST'])
def test_endpoint():
    """Simple test endpoint that returns what it receives"""
    return jsonify({
        'success': True,
        'message': 'Server is working!',
        'method': request.method,
        'url': request.url,
        'args': dict(request.args),
        'headers': dict(request.headers),
        'remote_addr': request.remote_addr,
        'user_id_received': request.args.get('user_id'),
        'server_time': datetime.now().isoformat()
    })

