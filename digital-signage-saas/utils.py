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


def update_device_heartbeat(device_id, device_name=None, device_info=None, user_id=None, from_setup=False):
    """Update device information for tenant. If device was removed from panel and from_setup is False, returns None (caller should respond with removed=True to APK).
    log_activity is called outside the lock to avoid blocking other heartbeats (DB commit can be slow)."""
    if user_id is None:
        user_id = current_user.id

    is_new_device = False
    with device_lock:
        removed = _get_removed_devices(user_id)
        if from_setup:
            _clear_removed_device(user_id, device_id)
        elif device_id in removed:
            return None  # Removed from panel; do not re-add. Caller returns removed=True to APK.

        devices = load_json_file('devices.json', {}, user_id)

        if device_id not in devices:
            is_new_device = True
            devices[device_id] = {
                'id': device_id,
                'name': device_name or f'Display {len(devices) + 1}',
                'first_seen': datetime.now().isoformat(),
                'current_video': None,
                'command_id': 0,
                'status': 'idle',
                'info': device_info or {}
            }

        devices[device_id]['last_seen'] = datetime.now().isoformat()

        if device_info:
            devices[device_id]['info'].update(device_info)

        save_json_file('devices.json', devices, user_id)
        result = devices[device_id]

    if is_new_device:
        log_activity('device_connected', {'device_id': device_id, 'name': device_name}, user_id)
    return result


def get_connected_devices(user_id=None):
    """Get list of online devices for tenant (within DEVICE_TIMEOUT)"""
    all_list = get_all_devices_with_status(user_id)
    return [d for d in all_list if d.get('online')]


def get_all_devices_with_status(user_id=None):
    """Get all devices for tenant with online/offline status. Names are stored per device.
    Devices are never removed by time or last_seen; they stay until the user removes them.
    Use a persistent DATA_DIR (e.g. on Render) so devices.json survives redeploys and offline devices remain visible."""
    if user_id is None:
        user_id = current_user.id
    
    devices = load_json_file('devices.json', {}, user_id)
    now = datetime.now()
    result = []
    
    for device_id, device_data in devices.items():
        try:
            row = dict(device_data)
            row['id'] = device_id
            last_seen = datetime.fromisoformat(device_data.get('last_seen', now.isoformat()))
            seconds_ago = (now - last_seen).total_seconds()
            row['online'] = seconds_ago <= Config.DEVICE_TIMEOUT
            if row['online']:
                row['last_seen_ago'] = int(seconds_ago)
            else:
                row['last_seen_ago'] = None
            result.append(row)
        except Exception:
            row = dict(device_data)
            row['id'] = device_id
            row['online'] = False
            row['last_seen_ago'] = None
            result.append(row)
    
    return result


def get_device_count(user_id=None):
    """Get total number of devices for tenant"""
    if user_id is None:
        user_id = current_user.id
    devices = load_json_file('devices.json', {}, user_id)
    return len(devices)


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
        }
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {'site_name': 'Digital Signage', 'support_email': '', 'default_trial_days': 7, 'maintenance_mode': False}


def save_admin_settings(settings):
    """Save admin settings to JSON file"""
    data_dir = os.path.join(Config.UPLOAD_FOLDER, '..')
    data_dir = os.path.normpath(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, 'admin_settings.json')
    with open(path, 'w') as f:
        json.dump(settings, f, indent=2)


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
