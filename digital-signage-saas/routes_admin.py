"""
Admin Routes - WordPress-style admin dashboard
"""
import os
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from functools import wraps
from models import db, User, PaymentHistory, ActivityLog
from datetime import datetime, timedelta
from utils import get_device_count, get_storage_usage

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/bootstrap')
def admin_bootstrap():
    """
    One-time endpoint to create/reset admin user on Render.
    Requires ?token=YOUR_ADMIN_BOOTSTRAP_TOKEN (set ADMIN_BOOTSTRAP_TOKEN in Render env).
    Use once, then remove ADMIN_BOOTSTRAP_TOKEN for security.
    """
    required_token = os.environ.get('ADMIN_BOOTSTRAP_TOKEN')
    if not required_token:
        return jsonify({'error': 'Bootstrap disabled (ADMIN_BOOTSTRAP_TOKEN not set)'}), 404
    if request.args.get('token') != required_token:
        return jsonify({'error': 'Invalid token'}), 403

    admin = User.query.filter_by(username='admin').first()
    if admin:
        admin.set_password('admin123')
        admin.email = 'admin@example.com'
        admin.is_admin = True
        admin.is_active = True
        admin.ensure_connection_code()
        db.session.commit()
        action = 'reset'
    else:
        admin = User(
            username='admin',
            email='admin@example.com',
            company_name='System Administrator',
            is_admin=True,
            plan='enterprise',
            subscription_status='active'
        )
        admin.set_password('admin123')
        admin.ensure_connection_code()
        db.session.add(admin)
        db.session.commit()
        action = 'created'

    return jsonify({
        'success': True,
        'action': action,
        'username': 'admin',
        'password': 'admin123',
        'message': 'Admin user ' + action + '. Login at /auth/login. Remove ADMIN_BOOTSTRAP_TOKEN from env for security.'
    })


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'error')
            return redirect(url_for('main.landing'))
        return f(*args, **kwargs)
    return decorated_function


def get_plan_badge_class(status):
    """Return badge CSS class for subscription status"""
    if status == 'active':
        return 'badge-success'
    if status == 'trial':
        return 'badge-warning'
    return 'badge-danger'


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
    """List all users with search"""
    page = request.args.get('page', 1, type=int)
    per_page = 25
    search = request.args.get('s', '').strip()
    
    query = User.query
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
                User.company_name.ilike(search_pattern),
                User.connection_code == search
            )
        )
    users = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('admin_users.html', users=users, search=search)


@admin_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_user_add():
    """Add new user"""
    from config import Config
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        company_name = request.form.get('company_name', '').strip()
        plan = request.form.get('plan', 'free')
        is_admin = request.form.get('is_admin') == 'on'
        
        if not username or not email or not password:
            flash('Username, email and password are required', 'error')
            return render_template('admin_user_add.html', plans=Config.PLANS)
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return render_template('admin_user_add.html', plans=Config.PLANS)
        if User.query.filter_by(username=username).first():
            flash(f'Username "{username}" already exists', 'error')
            return render_template('admin_user_add.html', plans=Config.PLANS)
        if User.query.filter_by(email=email).first():
            flash(f'Email "{email}" is already registered', 'error')
            return render_template('admin_user_add.html', plans=Config.PLANS)
        if plan not in Config.PLANS:
            plan = 'free'
        
        user = User(
            username=username, email=email, company_name=company_name,
            plan=plan, is_admin=is_admin,
            subscription_status='trial' if plan == 'free' else 'active',
            trial_ends_at=datetime.utcnow() + timedelta(days=7) if plan == 'free' else None
        )
        user.set_password(password)
        user.ensure_connection_code()
        db.session.add(user)
        db.session.commit()
        
        import os, json
        tenant_path = os.path.join('data/tenants', user.get_tenant_id())
        os.makedirs(os.path.join(tenant_path, 'content'), exist_ok=True)
        for fname, content in [
            ('devices.json', {}), ('playlist.json', {'videos': [], 'settings': {'interval': 30, 'loop': True}}),
            ('playlists.json', {'playlists': []}), ('schedules.json', {'schedules': []}),
            ('groups.json', {'groups': []}), ('analytics.json', {'events': [], 'stats': {}})
        ]:
            with open(os.path.join(tenant_path, fname), 'w') as f:
                json.dump(content, f, indent=2)
        
        flash(f'User "{username}" created successfully', 'success')
        return redirect(url_for('admin.admin_user_detail', user_id=user.id))
    
    from config import Config
    return render_template('admin_user_add.html', plans=Config.PLANS)


@admin_bp.route('/users/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_user_detail(user_id):
    """View/edit user details"""
    from config import Config
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        action = request.form.get('_action', 'save')
        if action == 'save':
            user.username = request.form.get('username', user.username).strip()
            user.email = request.form.get('email', user.email).strip()
            user.company_name = request.form.get('company_name', user.company_name or '').strip()
            user.plan = request.form.get('plan', user.plan) if request.form.get('plan') in Config.PLANS else user.plan
            user.subscription_status = request.form.get('subscription_status', user.subscription_status)
            user.is_active = request.form.get('is_active') == 'on'
            user.is_admin = request.form.get('is_admin') == 'on'
            new_pass = request.form.get('new_password', '')
            if new_pass and len(new_pass) >= 6:
                user.set_password(new_pass)
            db.session.commit()
            flash('User updated successfully', 'success')
        elif action == 'regenerate_code':
            user.connection_code = None
            user.ensure_connection_code()
            db.session.commit()
            flash(f'New connection code: {user.connection_code}', 'success')
        return redirect(url_for('admin.admin_user_detail', user_id=user_id))
    
    payments = PaymentHistory.query.filter_by(user_id=user.id).order_by(PaymentHistory.created_at.desc()).limit(20).all()
    activities = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.created_at.desc()).limit(50).all()
    device_count = get_device_count(user.id)
    storage_used = get_storage_usage(user.id)
    
    return render_template('admin_user_detail.html',
        user=user, payments=payments, activities=activities,
        device_count=device_count, storage_used=storage_used, plans=Config.PLANS
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
    next_url = request.args.get('next') or url_for('admin.admin_user_detail', user_id=user_id)
    return redirect(next_url)


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


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_user_delete(user_id):
    """Delete user (cannot delete self)"""
    if user_id == current_user.id:
        flash('You cannot delete your own account', 'error')
        return redirect(url_for('admin.admin_users'))
    user = User.query.get_or_404(user_id)
    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{username}" has been deleted', 'success')
    return redirect(url_for('admin.admin_users'))


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


@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    """Admin settings page"""
    if request.method == 'POST':
        # Placeholder for future settings (e.g. site name, support email)
        flash('Settings saved (no settings configured yet)', 'success')
        return redirect(url_for('admin.admin_settings'))
    return render_template('admin_settings.html')


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
