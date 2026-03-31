"""
Digital Signage SaaS Platform
Main Application File
"""
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, login_required, current_user
from sqlalchemy import text
from models import db, User, ActivityLog, PaymentHistory
from config import Config
import os
import json
import hashlib
import threading
import time
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import mimetypes

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Use absolute path for SQLite when DATABASE_URL not set (e.g. local dev)
if not os.environ.get('DATABASE_URL'):
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'signage.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
    # On Render/Heroku the filesystem is ephemeral: SQLite would be wiped every deploy
    if os.environ.get('RENDER') or os.environ.get('DYNO'):
        print('WARNING: DATABASE_URL is not set. Users and data will be LOST on each deploy. Add a persistent database (e.g. Render PostgreSQL) and set DATABASE_URL.')

CORS(app)

# Initialize extensions
db.init_app(app)


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


# ============================================================================
# RUN APPLICATION
# ============================================================================

if __name__ == '__main__':
    init_db()
    threading.Thread(target=schedule_checker, daemon=True).start()
    
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
