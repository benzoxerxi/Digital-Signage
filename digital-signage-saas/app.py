"""
Digital Signage SaaS Platform
Main Application File
"""
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, g
from flask_cors import CORS
from flask_login import LoginManager, login_required, current_user
try:
    from flask_migrate import Migrate
except Exception:
    Migrate = None
from sqlalchemy import text
from models import db, User, ActivityLog, PaymentHistory, TenantDisplay
from schema_migrations import migrate_tenant_displays_after_create_all
from config import Config
import os
import json
import hashlib
import threading
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from urllib import request as urllib_request
from werkzeug.utils import secure_filename
import mimetypes

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

def _enforce_database_runtime_policy():
    """Fail fast in production when DB config is unsafe."""
    db_url = (os.environ.get('DATABASE_URL') or '').strip()
    is_prod = bool(getattr(Config, 'IS_PRODUCTION', False))
    if is_prod and not db_url:
        raise RuntimeError(
            "DATABASE_URL is required in production. Refusing to start with ephemeral SQLite."
        )
    if is_prod and db_url.startswith('sqlite'):
        raise RuntimeError(
            "SQLite is not allowed in production. Configure PostgreSQL via DATABASE_URL."
        )
    if not db_url:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'signage.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path


_enforce_database_runtime_policy()

CORS(app)

# Initialize extensions
db.init_app(app)
if Migrate is not None:
    migrate = Migrate(app, db)

_METRIC_LOCK = threading.Lock()
_METRIC_COUNTS = defaultdict(int)
_METRIC_STATUS = defaultdict(int)
_METRIC_LATENCY_MS = defaultdict(list)
_CRITICAL_ENDPOINTS = {'/api/playback/state', '/api/playback/events', '/api/device_layout', '/api/playlist'}
_PROCESS_STARTED_AT = datetime.utcnow()
_LAST_ALERT_AT = {}
logger = logging.getLogger(__name__)


@app.before_request
def _metrics_before_request():
    g.request_started_at = time.perf_counter()


@app.after_request
def _metrics_after_request(response):
    started = getattr(g, 'request_started_at', None)
    if started is None:
        return response
    path = request.path
    if path in _CRITICAL_ENDPOINTS:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        with _METRIC_LOCK:
            _METRIC_COUNTS[path] += 1
            _METRIC_STATUS[f"{path}:{response.status_code}"] += 1
            bucket = _METRIC_LATENCY_MS[path]
            bucket.append(elapsed_ms)
            if len(bucket) > 500:
                del bucket[:-500]
        if response.status_code >= 500:
            _emit_ops_alert('api_5xx', {
                'path': path,
                'status': response.status_code,
                'latency_ms': round(elapsed_ms, 2),
            })
        elif elapsed_ms > 2500:
            _emit_ops_alert('api_slow', {
                'path': path,
                'status': response.status_code,
                'latency_ms': round(elapsed_ms, 2),
            })
    return response


def _emit_ops_alert(event_type, payload):
    webhook = app.config.get('ALERT_WEBHOOK_URL', '')
    if not webhook:
        return
    key = f"{event_type}:{payload.get('path', '')}:{payload.get('status', '')}"
    now = time.time()
    last = _LAST_ALERT_AT.get(key, 0)
    if now - last < 300:
        return
    _LAST_ALERT_AT[key] = now
    try:
        body = json.dumps({
            'event': event_type,
            'timestamp': datetime.utcnow().isoformat(),
            **payload,
        }).encode('utf-8')
        req = urllib_request.Request(
            webhook,
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib_request.urlopen(req, timeout=3).read()
    except Exception:
        pass


@app.route('/api/metrics')
@login_required
def get_metrics():
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403
    snapshot = {}
    with _METRIC_LOCK:
        for path in sorted(_CRITICAL_ENDPOINTS):
            vals = sorted(_METRIC_LATENCY_MS.get(path, []))
            count = len(vals)
            p95 = vals[min(count - 1, int(count * 0.95))] if count else 0.0
            avg = (sum(vals) / count) if count else 0.0
            snapshot[path] = {
                'requests': _METRIC_COUNTS.get(path, 0),
                'avg_ms': round(avg, 2),
                'p95_ms': round(p95, 2),
                'status': {
                    k.split(':')[-1]: v
                    for k, v in _METRIC_STATUS.items()
                    if k.startswith(f'{path}:')
                },
            }
    total_5xx = 0
    with _METRIC_LOCK:
        for k, v in _METRIC_STATUS.items():
            try:
                code = int(k.split(':')[-1])
            except Exception:
                continue
            if code >= 500:
                total_5xx += v
    return jsonify({
        'generated_at': datetime.utcnow().isoformat(),
        'process_started_at': _PROCESS_STARTED_AT.isoformat(),
        'uptime_seconds': int((datetime.utcnow() - _PROCESS_STARTED_AT).total_seconds()),
        'restart_count_observed': 1,
        'total_5xx': total_5xx,
        'critical_endpoints': snapshot,
    })


@app.context_processor
def inject_base_path():
    """Inject BASE_PATH into all templates so URLs can be prefixed when served under a subpath."""
    base_path = app.config.get('BASE_PATH', '')
    # Ensure empty string or a value starting with slash, without trailing slash
    if base_path and not base_path.startswith('/'):
        base_path = '/' + base_path
    base_path = base_path.rstrip('/')
    return {'BASE_PATH': base_path}

# Ensure tables exist and migrations run when app is loaded (e.g. under gunicorn)
with app.app_context():
    db.create_all()
    # Add new columns if missing (e.g. email verification, connection_code)
    for col, sql in [
        ('email_verified', 'ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT 1'),
        ('email_verify_token', 'ALTER TABLE users ADD COLUMN email_verify_token VARCHAR(64)'),
        ('email_verify_expires', 'ALTER TABLE users ADD COLUMN email_verify_expires DATETIME'),
        ('connection_code', 'ALTER TABLE users ADD COLUMN connection_code VARCHAR(9)'),
    ]:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception as e:
            if 'duplicate column' not in str(e).lower() and 'already exists' not in str(e).lower():
                print(f"Migration note ({col}): {e}")
            db.session.rollback()
    # Ensure all existing users have connection codes
    for user in User.query.filter(db.or_(User.connection_code.is_(None), User.connection_code == '')).all():
        user.ensure_connection_code()
        db.session.add(user)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

# Import utility functions
from utils import *

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ============================================================================
# SCHEDULE CHECKER (Background Thread)
# ============================================================================

def check_schedules_for_all_tenants():
    """Check and execute scheduled content for all active users"""
    with app.app_context():
        active_users = User.query.filter_by(is_active=True).all()
        
        for user in active_users:
            if not user.is_subscription_active():
                continue
            
            try:
                check_schedules_for_user(user.id)
            except Exception as e:
                print(f"Schedule check error for user {user.id}: {e}")


def check_schedules_for_user(user_id):
    """Check and execute scheduled content for specific user"""
    schedules = load_json_file('schedules.json', {'schedules': []}, user_id)
    now = datetime.now()
    current_time = now.strftime('%H:%M')
    current_day = now.strftime('%A').lower()
    
    for schedule in schedules.get('schedules', []):
        if not schedule.get('enabled', True):
            continue
        
        if schedule['time'] == current_time:
            if current_day in [d.lower() for d in schedule.get('days', [])]:
                content = schedule.get('content', {})
                device_ids = schedule.get('device_ids', [])
                
                if content.get('type') == 'video':
                    play_video_to_devices(content['filename'], device_ids, user_id)


def schedule_checker():
    """Background thread to check schedules"""
    while True:
        try:
            check_schedules_for_all_tenants()
        except Exception as e:
            print(f"Schedule checker error: {e}")
        time.sleep(60)  # Check every minute


def cleanup_runtime_state():
    """Periodic cleanup for stale screenshot blobs and old activity rows."""
    with app.app_context():
        now = datetime.utcnow()
        screenshot_cutoff = now - timedelta(hours=app.config.get('CLEANUP_SCREENSHOT_RETENTION_HOURS', 48))
        activity_cutoff = now - timedelta(days=app.config.get('CLEANUP_ACTIVITY_RETENTION_DAYS', 45))
        try:
            for row in TenantDisplay.query.all():
                ts = row.screenshot_timestamp
                if not ts:
                    continue
                try:
                    stamp = datetime.fromisoformat(ts)
                except Exception:
                    stamp = None
                if stamp is None or stamp < screenshot_cutoff:
                    if row.screenshot_data or row.screenshot_timestamp:
                        row.screenshot_data = None
                        row.screenshot_timestamp = None
                        row.state_version = int(row.state_version or 0) + 1
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            _emit_ops_alert('cleanup_error', {'scope': 'tenant_displays_screenshot', 'error': str(e)})

        try:
            deleted = ActivityLog.query.filter(ActivityLog.created_at < activity_cutoff).delete()
            db.session.commit()
            if deleted:
                print(f"Cleanup: pruned {deleted} old activity rows")
        except Exception as e:
            db.session.rollback()
            _emit_ops_alert('cleanup_error', {'scope': 'activity_log', 'error': str(e)})


def cleanup_worker():
    while True:
        try:
            cleanup_runtime_state()
        except Exception as e:
            _emit_ops_alert('cleanup_error', {'scope': 'worker', 'error': str(e)})
        time.sleep(max(300, int(app.config.get('CLEANUP_INTERVAL_SECONDS', 3600))))


# Schedule checker thread started after init_db() in main block


# ============================================================================
# IMPORT ROUTE BLUEPRINTS
# ============================================================================

# Import and register blueprints
from auth import auth_bp
app.register_blueprint(auth_bp, url_prefix='/auth')

# We'll create these in the next files
from routes_main import main_bp
app.register_blueprint(main_bp)

from routes_api import api_bp
app.register_blueprint(api_bp, url_prefix='/api')

try:
    from routes_google_drive import drive_bp
    app.register_blueprint(drive_bp)
except ImportError:
    pass  # Google Drive optional if deps not installed

from routes_admin import admin_bp
app.register_blueprint(admin_bp, url_prefix='/admin')


@app.before_request
def check_maintenance():
    """Redirect non-admins to maintenance page when maintenance mode is on"""
    try:
        settings = load_admin_settings()
        if not settings.get('maintenance_mode'):
            return
    except Exception:
        return
    if request.path.startswith('/admin') or request.path.startswith('/auth/login') or request.path.startswith('/auth/logout') or request.path.startswith('/static'):
        return
    if current_user.is_authenticated and current_user.is_admin:
        return
    return render_template('maintenance.html', settings=settings), 503


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_db():
    """Initialize database and create tables"""
    with app.app_context():
        db.create_all()
        
        # Migration: add connection_code column if upgrading from older version
        try:
            db.session.execute(text("ALTER TABLE users ADD COLUMN connection_code VARCHAR(9)"))
            db.session.commit()
        except Exception as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                print(f"Migration note: {e}")
            db.session.rollback()
        
        # Create admin user if doesn't exist (local dev; on Render use /admin/bootstrap)
        _admin_user = os.environ.get('ADMIN_USERNAME', 'admin').strip() or 'admin'
        _admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin123')
        admin = User.query.filter_by(username=_admin_user).first()
        if not admin:
            admin = User(
                username=_admin_user,
                email=f'{_admin_user}@example.com',
                company_name='System Administrator',
                is_admin=True,
                plan='paid',
                subscription_status='active'
            )
            admin.set_password(_admin_pass)
            admin.ensure_connection_code()
            db.session.add(admin)
            db.session.commit()
            print(f"✅ Admin user created (username: {_admin_user})")
            print("⚠️  CHANGE THE ADMIN PASSWORD in production!")
        
        # Ensure all existing users have connection codes (migration)
        for user in User.query.filter(db.or_(User.connection_code.is_(None), User.connection_code == '')).all():
            user.ensure_connection_code()
            db.session.add(user)
        db.session.commit()

        migrate_tenant_displays_after_create_all(db, app)


# ============================================================================
# RUN APPLICATION
# ============================================================================

if __name__ == '__main__':
    init_db()
    threading.Thread(target=schedule_checker, daemon=True).start()
    threading.Thread(target=cleanup_worker, daemon=True).start()
    
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print("=" * 80)
    print("🚀 DIGITAL SIGNAGE SAAS PLATFORM")
    print("=" * 80)
    print(f"🌐 Server URL: http://{local_ip}:5000")
    print(f"🏠 Local URL: http://localhost:5000")
    print("=" * 80)
    print("📱 Features:")
    print("   • Multi-tenant architecture")
    print("   • User authentication & registration")
    print("   • Subscription management")
    print("   • Digital signage control")
    print("   • Admin dashboard")
    print("=" * 80)
    
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
