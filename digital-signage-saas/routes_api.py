"""
API Routes for Digital Signage Control
Multi-tenant API endpoints
"""
from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from config import Config
from datetime import datetime
import os
import json

# Import helper functions from utils
from utils import (
    load_json_file, save_json_file, get_content_folder, get_data_file_path,
    allowed_file, get_file_hash, get_connected_devices, get_device_count,
    update_device_heartbeat, log_activity, get_storage_usage, device_lock
)

api_bp = Blueprint('api', __name__)


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
    content_folder = get_content_folder(user_id)
    if content_folder:
        for video in playlist.get('videos', []):
            filepath = os.path.join(content_folder, video['filename'])
            if os.path.exists(filepath):
                stat = os.stat(filepath)
                video['size'] = f"{stat.st_size / (1024*1024):.1f} MB"
                video['hash'] = get_file_hash(filepath)
    # APK expects videos with filename, name, url (full URL with code for APK)
    base_url = request.url_root.rstrip('/')
    for video in playlist.get('videos', []):
        if 'url' not in video or not video['url'].startswith('http'):
            video['url'] = f"{base_url}/api/video/{video['filename']}?code={code_param}" if code_param else f"{base_url}/api/video/{video['filename']}"

    return jsonify(playlist)




# ============================================================================
# PROGRAM LAYOUT FOR DEVICES (full-layout endpoint for APK)
# ============================================================================


@api_bp.route('/device_layout')
def get_device_layout():
    """Return full program layout (program + elements) for a device / connection code.

    This is used by the Android/TV APK to render full layouts instead of just a flat
    video playlist.

    Authentication:
      - Preferred: ?code=<9-digit-connection-code>
      - Legacy   : ?user_id=<user id>

    Response (example):
    {
      "deviceId": "192_168_1_10",
      "userId": 123,
      "program": {
        "id": "prog_123",
        "name": "Main Screen",
        "width": 1920,
        "height": 1080,
        "elements": [
          {
            "id": "el1",
            "type": "video",
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "zIndex": 0,
            "props": {
              "url": "https://.../api/video/file.mp4?code=...",
              "loop": true,
              "volume": 1.0
            }
          },
          ...
        ]
      }
    }
    """
    from models import User

    # Resolve user by connection code or user_id
    user = None
    code_param = request.args.get('code')
    if code_param:
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

    user_id = user.id

    # Device identity – mirror playback/state logic
    device_id = request.args.get('device_id')
    if not device_id:
        device_id = request.remote_addr.replace('.', '_')

    # Load currently active program playlist manifest for this tenant
    program_manifest = load_json_file('program_playlist.json', {
        'programs': [],
        'active_playlist_id': None,
        'active_playlist_name': None,
        'updated_at': None,
    }, user_id)

    program_ids = program_manifest.get('programs') or []
    if not program_ids:
        # No active program-based playlist; return empty program so APK can fall back.
        return jsonify({
            'deviceId': device_id,
            'userId': user_id,
            'program': None
        })

    # For now, use the first program in the active list
    active_program_id = program_ids[0]

    programs_data = load_json_file('programs.json', {'programs': []}, user_id)
    program = next((p for p in programs_data.get('programs', []) if p.get('id') == active_program_id), None)

    if not program:
        # Manifest references a program that no longer exists – treat as no layout.
        return jsonify({
            'deviceId': device_id,
            'userId': user_id,
            'program': None
        })

    # Build full video/image/text/webview element models with proper URLs for media
    base_url = request.url_root.rstrip('/')
    video_param = f'code={user.connection_code}' if user.connection_code else f'user_id={user_id}'

    elements_out = []
    for raw_el in program.get('elements', []):
        try:
            el_type = raw_el.get('type')
            props = raw_el.get('props') or {}

            el = {
                'id': raw_el.get('id'),
                'type': el_type,
                'x': float(raw_el.get('x', 0)),
                'y': float(raw_el.get('y', 0)),
                'width': float(raw_el.get('width', program.get('width', 1920))),
                'height': float(raw_el.get('height', program.get('height', 1080))),
                'zIndex': int(raw_el.get('zIndex', raw_el.get('z_index', 0))),
                'props': {}
            }

            if el_type == 'video':
                filename = props.get('filename') or props.get('file') or ''
                video_url = None
                if filename:
                    video_url = f"{base_url}/api/video/{filename}?{video_param}"
                el['props'] = {
                    'filename': filename,
                    'url': video_url,
                    'loop': bool(props.get('loop', True)),
                    'volume': float(props.get('volume', 1.0)),
                }
            elif el_type == 'image':
                filename = props.get('filename') or ''
                image_url = None
                if filename:
                    image_url = f"{base_url}/api/video/{filename}?{video_param}"
                el['props'] = {
                    'filename': filename,
                    'url': image_url,
                    'fit': props.get('fit', 'contain'),
                }
            elif el_type == 'text':
                el['props'] = {
                    'content': props.get('content', ''),
                    'fontSize': int(props.get('fontSize', 24)),
                    'color': props.get('color', '#FFFFFF'),
                    'alignment': props.get('alignment', 'left'),
                }
            elif el_type == 'webview':
                el['props'] = {
                    'url': props.get('url', ''),
                    'refreshSeconds': int(props.get('refreshSeconds', 0)),
                }
            else:
                # Unknown element type – include raw props so client can ignore or handle later.
                el['props'] = props

            elements_out.append(el)
        except Exception:
            # Skip any malformed element instead of failing the entire layout.
            continue

    # Sort by zIndex for stable ordering
    elements_out.sort(key=lambda e: e.get('zIndex', 0))

    out_program = {
        'id': program.get('id'),
        'name': program.get('name'),
        'width': program.get('width'),
        'height': program.get('height'),
        'elements': elements_out,
    }

    return jsonify({
        'deviceId': device_id,
        'userId': user_id,
        'program': out_program,
        'source_playlist_id': program_manifest.get('active_playlist_id'),
        'source_playlist_name': program_manifest.get('active_playlist_name'),
        'updated_at': program_manifest.get('updated_at'),
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
        
        # Update playlist
        playlist = load_json_file('playlist.json', {'videos': [], 'settings': {'interval': 30, 'loop': True}})
        
        if not any(v['filename'] == filename for v in playlist.get('videos', [])):
            playlist['videos'].append({
                'filename': filename,
                'name': filename,
                'added': datetime.now().isoformat(),
                'url': f'/api/video/{filename}'
            })
            save_json_file('playlist.json', playlist)
            log_activity('video_uploaded', {'filename': filename})
        
        return jsonify({'success': True, 'filename': filename})
    
    except Exception as e:
        print(f"Upload error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
    
    # Debug logging - see what the APK is sending
    print("=" * 50)
    print("PLAYBACK STATE REQUEST")
    print(f"Method: {request.method}")
    print(f"URL: {request.url}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Args: {dict(request.args)}")
    print(f"Form: {dict(request.form)}")
    print(f"JSON: {request.get_json(silent=True)}")
    print("=" * 50)
    
    device_id = request.args.get('device_id')
    if not device_id:
        # If no device_id, use IP address as device identifier
        device_id = request.remote_addr.replace('.', '_')
    
    device_name = request.args.get('device_name')
    
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
                'command_id': device_data['command_id'],
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
                'command_id': 0,
                'mode': 'manual',
                'last_update': datetime.now().isoformat(),
                'loop': True
            })
    
    # For Android APK - Use 9-digit connection code (preferred) or user_id (legacy)
    from models import User
    user = None
    connection_code = request.args.get('code')
    
    if connection_code:
        user = User.get_by_connection_code(connection_code)
    if not user:
        user_id_param = request.args.get('user_id')
        if user_id_param:
            try:
                user_id = int(user_id_param)
                user = User.query.get(user_id)
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
        return jsonify({
            'error': 'Database error',
            'message': str(e)
        }), 500
    
    user_id = user.id
    device_info = {
        'user_agent': request.headers.get('User-Agent', ''),
        'ip': request.remote_addr
    }
    
    try:
        device_data = update_device_heartbeat(device_id, device_name, device_info, user_id)
        
        # Load playlist settings
        playlist = load_json_file('playlist.json', {
            'videos': [], 
            'settings': {'interval': 30, 'loop': True},
            'active_playlist_id': None
        }, user_id)
        
        # Prefer code param for video URL (cleaner for APK)
        video_param = f'code={user.connection_code}' if user.connection_code else f'user_id={user_id}'
        # Include screenshot_requested and device_name so display can respond
        screenshot_requested = device_data.get('screenshot_requested', False)
        device_name_from_server = device_data.get('name')
        if device_data.get('current_video'):
            response = {
                'current_video': device_data['current_video'],
                'command_id': device_data['command_id'],
                'mode': 'auto' if len(playlist.get('videos', [])) > 1 else 'manual',
                'last_update': device_data.get('last_seen'),
                'video_url': f'/api/video/{device_data["current_video"]}?{video_param}',
                'device_id': device_id,
                'loop': playlist.get('settings', {}).get('loop', True),
                'interval': playlist.get('settings', {}).get('interval', 30),
                'screenshot_requested': screenshot_requested,
                'device_name': device_name_from_server
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
                'command_id': 0,
                'mode': 'manual',
                'last_update': device_data.get('last_seen', datetime.now().isoformat()),
                'device_id': device_id,
                'status': 'connected',
                'loop': True,
                'screenshot_requested': screenshot_requested,
                'device_name': device_name_from_server
            })
    except Exception as e:
        return jsonify({
            'error': 'Server error',
            'message': str(e)
        }), 500


@api_bp.route('/playback/play', methods=['POST'])
@login_required
def play_video():
    """Play a specific video on selected devices"""
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    
    data = request.json
    filename = data.get('filename')
    device_ids = data.get('device_ids', [])
    
    print("=" * 50)
    print("PLAY VIDEO REQUEST")
    print(f"Filename: {filename}")
    print(f"Device IDs requested: {device_ids}")
    print("=" * 50)
    
    if not filename:
        return jsonify({'success': False, 'error': 'No filename provided'}), 400
    
    content_folder = get_content_folder()
    filepath = os.path.join(content_folder, secure_filename(filename))
    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'Video not found'}), 404
    
    # Use tenant-scoped devices file so commands only affect current user's displays
    from flask_login import current_user as _cu
    devices = load_json_file('devices.json', {}, _cu.id)
    print(f"Available devices: {list(devices.keys())}")
    
    updated_count = 0
    
    if device_ids:
        for device_id in device_ids:
            if device_id in devices:
                devices[device_id]['current_video'] = filename
                devices[device_id]['command_id'] = devices[device_id].get('command_id', 0) + 1
                updated_count += 1
                print(f"✅ Updated device: {device_id}")
            else:
                print(f"❌ Device not found: {device_id}")
    else:
        # Play on all devices
        for device_id in devices:
            devices[device_id]['current_video'] = filename
            devices[device_id]['command_id'] = devices[device_id].get('command_id', 0) + 1
            print(f"✅ Updated device: {device_id} with video: {filename}")
        updated_count = len(devices)
    
    save_json_file('devices.json', devices, _cu.id)
    print(f"Total devices updated: {updated_count}")
    print("=" * 50)
    
    log_activity('video_played', {'filename': filename, 'device_count': updated_count})
    
    return jsonify({
        'success': True,
        'filename': filename,
        'devices_updated': updated_count,
        'target': 'selected' if device_ids else 'all'
    })


@api_bp.route('/playback/stop', methods=['POST'])
@login_required
def stop_playback():
    """Stop playback on all or selected devices"""
    data = request.json or {}
    device_ids = data.get('device_ids', [])
    
    from flask_login import current_user as _cu
    devices = load_json_file('devices.json', {}, _cu.id)
    updated_count = 0
    
    if device_ids:
        for device_id in device_ids:
            if device_id in devices:
                devices[device_id]['current_video'] = None
                devices[device_id]['status'] = 'idle'
                devices[device_id]['command_id'] = devices[device_id].get('command_id', 0) + 1
                updated_count += 1
    else:
        for device_id in devices:
            devices[device_id]['current_video'] = None
            devices[device_id]['status'] = 'idle'
            devices[device_id]['command_id'] = devices[device_id].get('command_id', 0) + 1
        updated_count = len(devices)
    
    save_json_file('devices.json', devices, _cu.id)
    log_activity('playback_stopped', {'device_count': updated_count})
    
    return jsonify({
        'success': True,
        'devices_updated': updated_count,
        'target': 'selected' if device_ids else 'all'
    })


@api_bp.route('/playback/next', methods=['POST', 'GET'])
def next_video():
    """Move to next video in playlist - called when current video ends"""
    
    # Resolve user: authenticated, code (9-digit), or user_id (legacy)
    from models import User
    user = None
    if current_user.is_authenticated:
        user = current_user
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
    
    user_id = user.id
    
    device_id = request.args.get('device_id')
    if not device_id:
        device_id = request.remote_addr.replace('.', '_')
    
    print(f"📹 Next video request from device: {device_id}")
    
    # Load playlist
    playlist = load_json_file('playlist.json', {
        'videos': [],
        'settings': {'interval': 30, 'loop': True}
    }, user_id)
    
    if not playlist.get('videos') or len(playlist['videos']) == 0:
        print(f"❌ No playlist active for user {user_id}")
        return jsonify({'success': False, 'error': 'No playlist active', 'action': 'repeat'}), 404
    
    # Load devices to get current video
    devices = load_json_file('devices.json', {}, user_id)
    
    if device_id not in devices:
        print(f"❌ Device not found: {device_id}")
        # Device not registered yet, play first video
        devices[device_id] = {
            'id': device_id,
            'name': f'Display {device_id[-6:]}',
            'first_seen': datetime.now().isoformat(),
            'last_seen': datetime.now().isoformat(),
            'current_video': playlist['videos'][0]['filename'],
            'command_id': 1,
            'status': 'playing',
            'info': {}
        }
        save_json_file('devices.json', devices, user_id)
        
        video_param = f'code={user.connection_code}' if user.connection_code else f'user_id={user_id}'
        return jsonify({
            'success': True,
            'next_video': playlist['videos'][0]['filename'],
            'current_index': 0,
            'total_videos': len(playlist['videos']),
            'video_url': f'/api/video/{playlist["videos"][0]["filename"]}?{video_param}'
        })
    
    current_video = devices[device_id].get('current_video')
    
    # Find current video index
    current_index = 0
    if current_video:
        for i, video in enumerate(playlist['videos']):
            if video['filename'] == current_video:
                current_index = i
                break
    
    # Get next video (loop back to start if at end)
    next_index = (current_index + 1) % len(playlist['videos'])
    next_video = playlist['videos'][next_index]['filename']
    
    # Update device
    devices[device_id]['current_video'] = next_video
    devices[device_id]['command_id'] = devices[device_id].get('command_id', 0) + 1
    devices[device_id]['last_seen'] = datetime.now().isoformat()
    
    save_json_file('devices.json', devices, user_id)
    
    print(f"✅ Auto-advance: {current_video} → {next_video} (index: {next_index}/{len(playlist['videos'])})")
    
    video_param = f'code={user.connection_code}' if user.connection_code else f'user_id={user_id}'
    return jsonify({
        'success': True,
        'next_video': next_video,
        'current_index': next_index,
        'total_videos': len(playlist['videos']),
        'video_url': f'/api/video/{next_video}?{video_param}',
        'loop': playlist.get('settings', {}).get('loop', True)
    })


# ============================================================================
# DEVICE MANAGEMENT
# ============================================================================

@api_bp.route('/devices')
@login_required
def get_devices():
    """Get list of all devices for current user"""
    from flask_login import current_user as _cu
    all_devices = load_json_file('devices.json', {}, _cu.id)
    connected = get_connected_devices(_cu.id)
    
    return jsonify({
        'devices': connected,
        'total': len(all_devices),
        'connected': len(connected)
    })


@api_bp.route('/devices/<device_id>', methods=['PUT'])
@login_required
def update_device(device_id):
    """Update device information"""
    data = request.json
    from flask_login import current_user as _cu
    devices = load_json_file('devices.json', {}, _cu.id)
    
    if device_id not in devices:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    
    if 'name' in data:
        devices[device_id]['name'] = data['name']
    
    save_json_file('devices.json', devices, _cu.id)
    return jsonify({'success': True, 'device': devices[device_id]})


@api_bp.route('/devices/<device_id>', methods=['DELETE'])
@login_required
def delete_device(device_id):
    """Remove a device"""
    from flask_login import current_user as _cu
    devices = load_json_file('devices.json', {}, _cu.id)
    
    if device_id in devices:
        del devices[device_id]
        save_json_file('devices.json', devices, _cu.id)
        log_activity('device_deleted', {'device_id': device_id})
    
    return jsonify({'success': True})


@api_bp.route('/devices/<device_id>/screenshot/request', methods=['POST'])
@login_required
def request_device_screenshot(device_id):
    """Set flag so the display will capture and upload a screenshot on next poll"""
    from flask_login import current_user as _cu
    devices = load_json_file('devices.json', {}, _cu.id)
    if device_id not in devices:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    devices[device_id]['screenshot_requested'] = True
    save_json_file('devices.json', devices, _cu.id)
    return jsonify({'success': True, 'message': 'Screenshot request sent to display'})


@api_bp.route('/devices/<device_id>/screenshot', methods=['GET'])
@login_required
def get_device_screenshot(device_id):
    """Return the latest screenshot for this device (if any)"""
    from flask_login import current_user as _cu
    devices = load_json_file('devices.json', {}, _cu.id)
    if device_id not in devices:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    data_url = devices[device_id].get('screenshot_data')
    timestamp = devices[device_id].get('screenshot_timestamp')
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

    with device_lock:
        devices = load_json_file('devices.json', {}, user_id)
        if device_id not in devices:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        devices[device_id]['screenshot_data'] = screenshot_b64
        devices[device_id]['screenshot_timestamp'] = datetime.now().isoformat()
        devices[device_id]['screenshot_requested'] = False
        save_json_file('devices.json', devices, user_id)
    return jsonify({'success': True, 'message': 'Screenshot received'})


@api_bp.route('/devices/format', methods=['POST'])
@login_required
def format_devices():
    """Format/reset selected devices"""
    data = request.json
    device_ids = data.get('device_ids', [])
    
    if not device_ids:
        return jsonify({'success': False, 'error': 'No devices specified'}), 400
    
    devices = load_json_file('devices.json', {})
    formatted_count = 0
    
    for device_id in device_ids:
        if device_id in devices:
            devices[device_id] = {
                'id': device_id,
                'name': f'Display {device_id[-4:]}',
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'current_video': None,
                'command_id': 0,
                'status': 'idle',
                'info': {},
                'online': False
            }
            formatted_count += 1
            log_activity('device_formatted', {'device_id': device_id})
    
    save_json_file('devices.json', devices)
    
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
    """Get or create playlists.

    Playlists can now include both raw videos (filenames) and program IDs.
    The existing 'videos' field is kept for backwards compatibility, and
    an optional 'programs' list stores associated program IDs.
    """
    if request.method == 'GET':
        return jsonify(load_json_file('playlists.json', {'playlists': []}))
    
    if not current_user.is_subscription_active():
        return jsonify({'success': False, 'error': 'Subscription expired'}), 403
    
    data = request.json or {}
    playlists = load_json_file('playlists.json', {'playlists': []})
    
    import time
    new_playlist = {
        'id': f'playlist_{int(time.time())}',
        'name': data.get('name') or 'Untitled playlist',
        'videos': data.get('videos') or [],
        'programs': data.get('programs') or [],
        'created': datetime.now().isoformat()
    }
    
    playlists['playlists'].append(new_playlist)
    save_json_file('playlists.json', playlists)
    log_activity('playlist_created', {'playlist_id': new_playlist['id']})
    
    return jsonify({'success': True, 'playlist': new_playlist})


@api_bp.route('/program_playlists/<playlist_id>/activate', methods=['POST'])
@login_required
def activate_program_playlist(playlist_id):
    """Activate just the program portion of a playlist.

    1) Writes a simple manifest to program_playlist.json with the ordered list of program IDs.
    2) Also compiles all video filenames referenced by those programs into playlist.json so
       existing video-only players (APK) still have something to play.
    """
    playlists_data = load_json_file('playlists.json', {'playlists': []})
    playlist = next((p for p in playlists_data['playlists'] if p['id'] == playlist_id), None)
    if not playlist:
        return jsonify({'success': False, 'error': 'Playlist not found'}), 404
    
    programs = playlist.get('programs') or []
    manifest = {
        'programs': programs,
        'active_playlist_id': playlist_id,
        'active_playlist_name': playlist.get('name'),
        'updated_at': datetime.now().isoformat()
    }
    save_json_file('program_playlist.json', manifest)

    # Compile all video filenames used inside the selected programs so the
    # existing Android player (which only understands videos) can still play them.
    video_filenames = []
    if programs:
        programs_data = load_json_file('programs.json', {'programs': []})
        for pid in programs:
            program = next((p for p in programs_data.get('programs', []) if p.get('id') == pid), None)
            if not program:
                continue
            for el in program.get('elements', []):
                try:
                    if el.get('type') != 'video':
                        continue
                    props = el.get('props') or {}
                    filename = props.get('filename')
                    if filename and filename not in video_filenames:
                        video_filenames.append(filename)
                except Exception:
                    continue

    video_count = 0
    if video_filenames:
        # Load / build main playlist.json just like activate_playlist()
        main_playlist = load_json_file('playlist.json', {
            'videos': [],
            'settings': {'interval': 30, 'loop': True},
            'active_playlist_id': None,
            'active_playlist_name': None
        })
        content_folder = get_content_folder()
        video_objects = []
        if content_folder:
            for video_filename in video_filenames:
                filepath = os.path.join(content_folder, video_filename)
                if os.path.exists(filepath):
                    stat = os.stat(filepath)
                    video_objects.append({
                        'filename': video_filename,
                        'name': video_filename,
                        'added': datetime.now().isoformat(),
                        'url': f'/api/video/{video_filename}',
                        'size': f"{stat.st_size / (1024*1024):.1f} MB"
                    })
        if video_objects:
            main_playlist['videos'] = video_objects
            main_playlist['active_playlist_id'] = playlist_id
            main_playlist['active_playlist_name'] = playlist.get('name')
            save_json_file('playlist.json', main_playlist)
            video_count = len(video_objects)

    log_activity('program_playlist_activated', {
        'playlist_id': playlist_id,
        'program_count': len(programs),
        'compiled_videos': video_filenames
    })
    return jsonify({
        'success': True,
        'program_count': len(programs),
        'video_count': video_count,
        'compiled_videos': video_filenames,
        'playlist_name': playlist.get('name')
    })


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
        
        # Load main playlist
        main_playlist = load_json_file('playlist.json', {
            'videos': [], 
            'settings': {'interval': 30, 'loop': True},
            'active_playlist_id': None,
            'active_playlist_name': None
        })
        
        # Get content folder to build full video objects
        content_folder = get_content_folder()
        video_objects = []
        
        for video_filename in playlist['videos']:
            filepath = os.path.join(content_folder, video_filename)
            if os.path.exists(filepath):
                stat = os.stat(filepath)
                video_objects.append({
                    'filename': video_filename,
                    'name': video_filename,
                    'added': datetime.now().isoformat(),
                    'url': f'/api/video/{video_filename}',
                    'size': f"{stat.st_size / (1024*1024):.1f} MB"
                })
        
        if len(video_objects) == 0:
            return jsonify({'success': False, 'error': 'No valid videos in playlist'}), 400
        
        # Update main playlist with this playlist's videos
        main_playlist['videos'] = video_objects
        main_playlist['active_playlist_id'] = playlist_id
        main_playlist['active_playlist_name'] = playlist['name']
        
        save_json_file('playlist.json', main_playlist)
        
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
# SCREEN LAYOUT (custom size + video layers)
# ============================================================================

@api_bp.route('/layout', methods=['GET'])
@login_required
def get_layout():
    """Get screen layout config (size + layers) for current user"""
    data = load_json_file('layout.json', {
        'screen_width': 1920,
        'screen_height': 1080,
        'layers': []
    })
    return jsonify(data)


@api_bp.route('/layout', methods=['POST'])
@login_required
def save_layout():
    """Save screen layout config (size + layers)"""
    data = request.get_json() or {}
    screen_width = int(data.get('screen_width', 1920))
    screen_height = int(data.get('screen_height', 1080))
    layers = data.get('layers', [])
    # Clamp size
    screen_width = max(320, min(7680, screen_width))
    screen_height = max(240, min(4320, screen_height))
    # Normalize layers: each has video, x, y, width, height, z_index
    out_layers = []
    for i, L in enumerate(layers):
        out_layers.append({
            'id': L.get('id') or f'layer_{i}',
            'video': L.get('video') or '',
            'x': float(L.get('x', 0)),
            'y': float(L.get('y', 0)),
            'width': float(L.get('width', 100)),
            'height': float(L.get('height', 100)),
            'width_units': L.get('width_units') or '%',
            'height_units': L.get('height_units') or '%',
            'z_index': int(L.get('z_index', i)),
        })
    out_layers.sort(key=lambda x: x['z_index'])
    layout = {
        'screen_width': screen_width,
        'screen_height': screen_height,
        'layers': out_layers,
    }
    save_json_file('layout.json', layout)
    log_activity('layout_updated', {'screen_width': screen_width, 'screen_height': screen_height, 'layers_count': len(out_layers)})
    return jsonify({'success': True, 'layout': layout})


# ============================================================================
# PROGRAMS (create program = name + size, then workspace with elements)
# ============================================================================

import uuid

@api_bp.route('/programs', methods=['GET'])
@login_required
def list_programs():
    """List all programs for current user"""
    data = load_json_file('programs.json', {'programs': []})
    return jsonify(data)


@api_bp.route('/programs', methods=['POST'])
@login_required
def create_program():
    """Create a new program (name + width, height). Returns the new program with id."""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    width = int(data.get('width', 1920))
    height = int(data.get('height', 1080))
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    width = max(320, min(7680, width))
    height = max(240, min(4320, height))
    programs_data = load_json_file('programs.json', {'programs': []})
    program_id = str(uuid.uuid4())[:8]
    program = {
        'id': program_id,
        'name': name,
        'width': width,
        'height': height,
        'elements': []
    }
    programs_data['programs'].append(program)
    save_json_file('programs.json', programs_data)
    log_activity('program_created', {'program_id': program_id, 'name': name})
    return jsonify({'success': True, 'program': program})


@api_bp.route('/programs/<program_id>')
@login_required
def get_program(program_id):
    """Get one program by id"""
    data = load_json_file('programs.json', {'programs': []})
    program = next((p for p in data['programs'] if p['id'] == program_id), None)
    if not program:
        return jsonify({'error': 'Program not found'}), 404
    return jsonify(program)


@api_bp.route('/programs/<program_id>', methods=['PUT'])
@login_required
def update_program(program_id):
    """Update program (name, size, elements)"""
    data = request.get_json() or {}
    programs_data = load_json_file('programs.json', {'programs': []})
    program = next((p for p in programs_data['programs'] if p['id'] == program_id), None)
    if not program:
        return jsonify({'error': 'Program not found'}), 404
    if 'name' in data and data['name'] is not None:
        program['name'] = str(data['name']).strip() or program['name']
    if 'width' in data:
        program['width'] = max(320, min(7680, int(data['width'])))
    if 'height' in data:
        program['height'] = max(240, min(4320, int(data['height'])))
    if 'elements' in data:
        program['elements'] = data['elements']
    save_json_file('programs.json', programs_data)
    return jsonify({'success': True, 'program': program})


@api_bp.route('/programs/<program_id>', methods=['DELETE'])
@login_required
def delete_program(program_id):
    """Delete a program"""
    programs_data = load_json_file('programs.json', {'programs': []})
    programs_data['programs'] = [p for p in programs_data['programs'] if p['id'] != program_id]
    save_json_file('programs.json', programs_data)
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
    """Get server status for current user"""
    if current_user.is_authenticated:
        playlist = load_json_file('playlist.json', {'videos': [], 'settings': {'interval': 30, 'loop': True}})
        
        return jsonify({
            'online': True,
            'video_count': len(playlist.get('videos', [])),
            'connected_devices': len(get_connected_devices()),
            'subscription_active': current_user.is_subscription_active(),
            'plan': current_user.plan,
            'server_time': datetime.now().isoformat()
        })
    else:
        return jsonify({
            'online': True,
            'server_time': datetime.now().isoformat(),
            'message': 'Server is running'
        })


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

