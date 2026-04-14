"""
Admin Routes - Super admin dashboard
"""
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from functools import wraps
from models import db, User, PaymentHistory, ActivityLog
from datetime import datetime, timedelta
from utils import get_device_count, get_storage_usage

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'error')
            return redirect(url_for('main.landing'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@login_required
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    # Get stats
    total_users = User.query.count()
    active_subscriptions = User.query.filter_by(subscription_status='active').count()
    trial_users = User.query.filter_by(subscription_status='trial').count()
    
    # Recent registrations
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    
    # Revenue calculation (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_payments = PaymentHistory.query.filter(
        PaymentHistory.created_at >= thirty_days_ago,
        PaymentHistory.status == 'succeeded'
    ).all()
    
    monthly_revenue = sum(p.amount for p in recent_payments)
    
    # Plan distribution
    from config import Config
    plan_stats = {}
    for plan_key in Config.PLANS.keys():
        plan_stats[plan_key] = User.query.filter_by(plan=plan_key).count()
    
    return render_template('admin_dashboard.html',
        total_users=total_users,
        active_subscriptions=active_subscriptions,
        trial_users=trial_users,
        monthly_revenue=monthly_revenue,
        recent_users=recent_users,
        plan_stats=plan_stats
    )


@admin_bp.route('/users')
@login_required
@admin_required
def admin_users():
    """List all users"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    users = User.query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin_users.html', users=users)


@admin_bp.route('/users/<int:user_id>')
@login_required
@admin_required
def admin_user_detail(user_id):
    """View user details"""
    user = User.query.get_or_404(user_id)
    
    # Get user's payments
    payments = PaymentHistory.query.filter_by(user_id=user.id)\
        .order_by(PaymentHistory.created_at.desc()).limit(20).all()
    
    # Get user's activities
    activities = ActivityLog.query.filter_by(user_id=user.id)\
        .order_by(ActivityLog.created_at.desc()).limit(50).all()
    
    # Get device count
    device_count = get_device_count(user.id)
    storage_used = get_storage_usage(user.id)
    
    return render_template('admin_user_detail.html',
        user=user,
        payments=payments,
        activities=activities,
        device_count=device_count,
        storage_used=storage_used
    )


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_user_active(user_id):
    """Activate/deactivate user"""
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    
    status = "activated" if user.is_active else "deactivated"
    flash(f'User {user.username} has been {status}', 'success')
    return redirect(url_for('admin.admin_user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/change-plan', methods=['POST'])
@login_required
@admin_required
def change_user_plan(user_id):
    """Change user's plan"""
    user = User.query.get_or_404(user_id)
    new_plan = request.form.get('plan')
    
    from config import Config
    if new_plan not in Config.PLANS:
        flash('Invalid plan', 'error')
        return redirect(url_for('admin.admin_user_detail', user_id=user_id))
    
    user.plan = new_plan
    user.subscription_status = 'active'
    db.session.commit()
    
    flash(f'User plan changed to {Config.PLANS[new_plan]["name"]}', 'success')
    return redirect(url_for('admin.admin_user_detail', user_id=user_id))


@admin_bp.route('/analytics')
@login_required
@admin_required
def admin_analytics():
    """System-wide analytics"""
    # User growth over time (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    daily_signups = db.session.query(
        db.func.date(User.created_at).label('date'),
        db.func.count(User.id).label('count')
    ).filter(User.created_at >= thirty_days_ago)\
     .group_by(db.func.date(User.created_at))\
     .all()
    
    # Revenue over time
    daily_revenue = db.session.query(
        db.func.date(PaymentHistory.created_at).label('date'),
        db.func.sum(PaymentHistory.amount).label('total')
    ).filter(
        PaymentHistory.created_at >= thirty_days_ago,
        PaymentHistory.status == 'succeeded'
    ).group_by(db.func.date(PaymentHistory.created_at))\
     .all()
    
    return render_template('admin_analytics.html',
        daily_signups=daily_signups,
        daily_revenue=daily_revenue
    )


@admin_bp.route('/payments')
@login_required
@admin_required
def admin_payments():
    """View all payments"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    payments = PaymentHistory.query.order_by(PaymentHistory.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin_payments.html', payments=payments)
