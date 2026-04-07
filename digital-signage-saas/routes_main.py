"""
Main routes - Landing page, Pricing, Dashboard, Subscriptions
"""
import os
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash, current_app
from flask_login import login_required, current_user
from config import Config

main_bp = Blueprint('main', __name__)


def _static_apk_mtime(filename: str):
    """Last filesystem modification time of an APK under static/apk/ (when the file was last replaced on server)."""
    folder = current_app.static_folder
    if not folder:
        return None
    path = os.path.join(folder, 'apk', filename)
    if os.path.isfile(path):
        return datetime.fromtimestamp(os.path.getmtime(path))
    return None

@main_bp.route('/')
def landing():
    """Homepage / Landing page"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    return render_template('landing.html', plans=Config.PLANS)


@main_bp.route('/pricing')
def pricing():
    """Pricing page"""
    return render_template('pricing.html', plans=Config.PLANS)


@main_bp.route('/rules')
def rules():
    """Rules and terms for free vs paid users"""
    return render_template('rules.html', plans=Config.PLANS)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Customer dashboard"""
    # Check subscription status
    if not current_user.is_subscription_active():
        return render_template('subscription_expired.html', user=current_user)
    
    return render_template('dashboard.html', user=current_user)


@main_bp.route('/program-editor/<program_id>')
@login_required
def program_editor(program_id):
    """Visual program editor with drag-and-drop canvas"""
    if not current_user.is_subscription_active():
        return render_template('subscription_expired.html', user=current_user)
    return render_template('program_editor.html', user=current_user, program_id=program_id)


@main_bp.route('/account', methods=['GET'])
@login_required
def account():
    """Account settings page"""
    from models import PaymentHistory, db
    
    current_user.ensure_connection_code()
    db.session.commit()
    
    payments = PaymentHistory.query.filter_by(user_id=current_user.id)\
        .order_by(PaymentHistory.created_at.desc()).limit(10).all()

    player_apk_mtime = _static_apk_mtime('Signage Player.apk')
    watchdog_apk_mtime = _static_apk_mtime('watchdog.apk')

    return render_template(
        'account.html',
        user=current_user,
        payments=payments,
        plans=Config.PLANS,
        player_apk_mtime=player_apk_mtime,
        watchdog_apk_mtime=watchdog_apk_mtime,
    )


@main_bp.route('/account/update', methods=['POST'])
@login_required
def account_update():
    """Update profile: username, email, company_name"""
    from models import db, User
    
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    company_name = request.form.get('company_name', '').strip()
    
    if not username:
        flash('Username is required', 'error')
        return redirect(url_for('main.account'))
    if not email:
        flash('Email is required', 'error')
        return redirect(url_for('main.account'))
    
    other_username = User.query.filter(User.username == username, User.id != current_user.id).first()
    if other_username:
        flash('Username is already in use', 'error')
        return redirect(url_for('main.account'))
    
    other_email = User.query.filter(User.email == email, User.id != current_user.id).first()
    if other_email:
        flash('Email is already in use', 'error')
        return redirect(url_for('main.account'))
    
    current_user.username = username
    current_user.email = email
    current_user.company_name = company_name if company_name else None
    db.session.commit()
    flash('Profile updated successfully', 'success')
    return redirect(url_for('main.account'))


@main_bp.route('/account/change-password', methods=['POST'])
@login_required
def account_change_password():
    """Change password (requires current password)"""
    from models import db
    
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    if not current_password:
        flash('Current password is required', 'error')
        return redirect(url_for('main.account'))
    if not current_user.check_password(current_password):
        flash('Current password is incorrect', 'error')
        return redirect(url_for('main.account'))
    if not new_password or len(new_password) < 6:
        flash('New password must be at least 6 characters', 'error')
        return redirect(url_for('main.account'))
    if new_password != confirm_password:
        flash('New password and confirmation do not match', 'error')
        return redirect(url_for('main.account'))
    
    current_user.set_password(new_password)
    db.session.commit()
    flash('Password changed successfully', 'success')
    return redirect(url_for('main.account'))


@main_bp.route('/subscriptions')
@login_required
def subscriptions():
    """Subscriptions page - view current plan and pay via Payoneer"""
    from utils import load_admin_settings
    settings = load_admin_settings()
    return render_template('subscriptions.html', user=current_user, plans=Config.PLANS,
        payoneer_email=settings.get('payoneer_email', ''),
        payoneer_instructions=settings.get('payoneer_instructions', ''),
        support_email=settings.get('support_email', ''))


