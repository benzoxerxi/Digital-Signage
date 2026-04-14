"""
Digital Signage SaaS Platform
Main Application File
"""
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, login_required, current_user
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
CORS(app)

# Initialize extensions
db.init_app(app)
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


# Start schedule checker thread
threading.Thread(target=schedule_checker, daemon=True).start()


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

from routes_admin import admin_bp
app.register_blueprint(admin_bp, url_prefix='/admin')


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_db():
    """Initialize database and create tables"""
    with app.app_context():
        db.create_all()
        
        # Create admin user if doesn't exist
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@example.com',
                company_name='System Administrator',
                is_admin=True,
                plan='enterprise',
                subscription_status='active'
            )
            admin.set_password('admin123')  # CHANGE THIS!
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin user created (username: admin, password: admin123)")
            print("⚠️  CHANGE THE ADMIN PASSWORD IMMEDIATELY!")


# ============================================================================
# RUN APPLICATION
# ============================================================================

if __name__ == '__main__':
    init_db()
    
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
