"""
Main routes - Landing page, Pricing, Dashboard
"""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from config import Config

main_bp = Blueprint('main', __name__)

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


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Customer dashboard"""
    # Check subscription status
    if not current_user.is_subscription_active():
        return render_template('subscription_expired.html', user=current_user)
    
    return render_template('dashboard.html', user=current_user)


@main_bp.route('/account')
@login_required
def account():
    """Account settings page"""
    from models import PaymentHistory
    
    payments = PaymentHistory.query.filter_by(user_id=current_user.id)\
        .order_by(PaymentHistory.created_at.desc()).limit(10).all()
    
    return render_template('account.html', user=current_user, payments=payments, plans=Config.PLANS)
