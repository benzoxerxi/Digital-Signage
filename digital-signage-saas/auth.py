"""
Authentication routes - Login, Registration, Logout
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from datetime import datetime, timedelta
import os

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration (no plan selection; no email verification)"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        company_name = request.form.get('company_name', '').strip()
        
        # Validation
        if not username or not email or not password:
            flash('All fields are required', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return render_template('register.html')
        
        # Check if user exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        # Create user (plan defaults to free; upgrade via Subscriptions)
        user = User(
            username=username,
            email=email,
            company_name=company_name,
            plan='free',
            subscription_status='trial',
            trial_ends_at=datetime.utcnow() + timedelta(days=7),
            email_verified=True
        )
        user.set_password(password)
        user.ensure_connection_code()
        
        db.session.add(user)
        db.session.commit()
        
        # Create tenant folder structure (may fail on read-only filesystem e.g. some PaaS)
        try:
            import json
            tenant_id = user.get_tenant_id()
            tenant_path = os.path.join('data', 'tenants', tenant_id)
            os.makedirs(os.path.join(tenant_path, 'content'), exist_ok=True)
            default_files = {
                'devices.json': {},
                'playlists.json': {'playlists': []},
                'schedules.json': {'schedules': []},
                'groups.json': {'groups': []},
                'analytics.json': {'events': [], 'stats': {}}
            }
            for filename, content in default_files.items():
                filepath = os.path.join(tenant_path, filename)
                with open(filepath, 'w') as f:
                    json.dump(content, f, indent=2)
        except Exception as e:
            import logging
            logging.warning(f"Tenant folder creation skipped (e.g. ephemeral filesystem): {e}")
        
        login_user(user)
        flash(f'Welcome {username}! Your 7-day free trial has started.', 'success')
        return redirect(url_for('main.dashboard'))
    
    return render_template('register.html')


@auth_bp.route('/verification-sent')
def verification_sent():
    """Redirect to login (email verification disabled)."""
    return redirect(url_for('auth.login'))


@auth_bp.route('/verify-email')
def verify_email():
    """Redirect to login (email verification disabled)."""
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-verification', methods=['GET', 'POST'])
def resend_verification():
    """Redirect to login (email verification disabled)."""
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated. Contact support.', 'error')
                return render_template('login.html')
            
            login_user(user, remember=remember)
            
            # Redirect to admin or dashboard
            next_page = request.args.get('next')
            if user.is_admin:
                return redirect(next_page or url_for('admin.admin_dashboard'))
            return redirect(next_page or url_for('main.dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('main.landing'))
