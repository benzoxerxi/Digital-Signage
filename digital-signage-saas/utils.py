"""
Utility functions shared across the application
This prevents circular imports
"""
import os
import json
import hashlib
import threading
from datetime import datetime
from flask_login import current_user
from config import Config

# Global lock for device operations
device_lock = threading.Lock()


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
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except:
        return default


def save_json_file(filename, data, user_id=None):
    """Save JSON file for specific tenant"""
    filepath = get_data_file_path(filename, user_id)
    if not filepath:
        return False
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    return True


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


def update_device_heartbeat(device_id, device_name=None, device_info=None, user_id=None):
    """Update device information for tenant"""
    if user_id is None:
        user_id = current_user.id
    
    with device_lock:
        devices = load_json_file('devices.json', {}, user_id)
        
        if device_id not in devices:
            devices[device_id] = {
                'id': device_id,
                'name': device_name or f'Display {len(devices) + 1}',
                'first_seen': datetime.now().isoformat(),
                'current_video': None,
                'command_id': 0,
                'status': 'idle',
                'info': device_info or {}
            }
            log_activity('device_connected', {'device_id': device_id, 'name': device_name}, user_id)
        
        devices[device_id]['last_seen'] = datetime.now().isoformat()
        
        if device_name:
            devices[device_id]['name'] = device_name
        
        if device_info:
            devices[device_id]['info'].update(device_info)
        
        save_json_file('devices.json', devices, user_id)
        return devices[device_id]


def get_connected_devices(user_id=None):
    """Get list of online devices for tenant"""
    if user_id is None:
        user_id = current_user.id
    
    devices = load_json_file('devices.json', {}, user_id)
    now = datetime.now()
    
    connected = []
    for device_id, device_data in devices.items():
        try:
            last_seen = datetime.fromisoformat(device_data['last_seen'])
            seconds_ago = (now - last_seen).total_seconds()
            
            if seconds_ago <= Config.DEVICE_TIMEOUT:
                device_data['online'] = True
                device_data['last_seen_ago'] = int(seconds_ago)
                connected.append(device_data)
            else:
                device_data['online'] = False
        except:
            device_data['online'] = False
    
    return connected


def get_device_count(user_id=None):
    """Get total number of devices for tenant"""
    if user_id is None:
        user_id = current_user.id
    devices = load_json_file('devices.json', {}, user_id)
    return len(devices)


def play_video_to_devices(filename, device_ids, user_id):
    """Play video on specified devices for user"""
    devices = load_json_file('devices.json', {}, user_id)
    
    if device_ids:
        for device_id in device_ids:
            if device_id in devices:
                devices[device_id]['current_video'] = filename
                devices[device_id]['command_id'] = devices[device_id].get('command_id', 0) + 1
    else:
        for device_id in devices:
            devices[device_id]['current_video'] = filename
            devices[device_id]['command_id'] = devices[device_id].get('command_id', 0) + 1
    
    save_json_file('devices.json', devices, user_id)
    log_activity('video_played', {
        'filename': filename,
        'device_count': len(device_ids) if device_ids else len(devices)
    }, user_id)
