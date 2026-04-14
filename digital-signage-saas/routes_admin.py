"""
Admin Routes - WordPress-style admin dashboard
"""
import os
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from functools import wraps
from models import db, User, PaymentHistory, ActivityLog
from datetime import datetime, timedelta
from utils import get_device_count, get_storage_usage, get_total_devices_all_users, get_total_storage_all_users, load_admin_settings, save_admin_settings

admin_bp = Blueprint('admin', __name__)


def _csv_escape(value):
    """Escape a value for CSV (RFC 4180): quote and escape if contains comma, quote, or newline"""
    if value is None:
        return ''
    s = str(value)
    if ',' in s or '"' in s or '\n' in s or '\r' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _get_bootstrap_admin_credentials():
    """Admin username/password from env; defaults: admin / admin123."""
    username = (os.environ.get('ADMIN_USERNAME') or 'admin').strip()
    password = os.environ.get('ADMIN_PASSWORD') or 'admin123'
    if not username:
        username = 'admin'
    return username, password


@admin_bp.route('/bootstrap/check')
def admin_bootstrap_check():
    """
    Safe diagnostic: returns whether the bootstrap admin user exists.
    Uses ADMIN_USERNAME if set, else 'admin'.
    """
    admin_username, _ = _get_bootstrap_admin_credentials()
    admin = User.query.filter_by(username=admin_username).first()
    return jsonify({'admin_exists': admin is not None})


@admin_bp.route('/bootstrap')
def admin_bootstrap():
    """
    One-time endpoint to create/reset admin user on Render.
    Requires ?token=YOUR_ADMIN_BOOTSTRAP_TOKEN (set ADMIN_BOOTSTRAP_TOKEN in Render env).
    Optional: set ADMIN_USERNAME and ADMIN_PASSWORD to use a different admin login.
    Use once, then remove ADMIN_BOOTSTRAP_TOKEN for security.
    """
    required_token = os.environ.get('ADMIN_BOOTSTRAP_TOKEN')
    if not required_token:
        return jsonify({'error': 'Bootstrap disabled (ADMIN_BOOTSTRAP_TOKEN not set)'}), 404
    if request.args.get('token') != required_token:
        return jsonify({'error': 'Invalid token'}), 403

    admin_username, admin_password = _get_bootstrap_admin_credentials()
    if len(admin_password) < 6:
        return jsonify({'error': 'ADMIN_PASSWORD must be at least 6 characters'}), 400

    admin = User.query.filter_by(username=admin_username).first()
    if admin:
        admin.set_password(admin_password)
        admin.email = admin.email or f'{admin_username}@example.com'
        admin.is_admin = True
        admin.is_active = True
        admin.ensure_connection_code()
        db.session.commit()
        action = 'reset'
    else:
        admin = User(
            username=admin_username,
            email=f'{admin_username}@example.com',
            company_name='System Administrator',
            is_admin=True,
            plan='paid',
            subscription_status='active'
        )
        admin.set_password(admin_password)
        admin.ensure_connection_code()
        db.session.add(admin)
        db.session.commit()
        action = 'created'

    return jsonify({
        'success': True,
        'action': action,
        'username': admin_username,
        'password': admin_password,
        'message': f'Admin user "{admin_username}" {action}. Login at /auth/login. Remove ADMIN_BOOTSTRAP_TOKEN from env for security.'
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
    from config import Config
    total_users = User.query.count()
    active_subscriptions = User.query.filter_by(subscription_status='active').count()
    trial_users = User.query.filter_by(subscription_status='trial').count()
    expired_users = User.query.filter(User.subscription_status.in_(['expired', 'canceled'])).count()
    inactive_users = User.query.filter_by(is_active=False).count()

    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_payments = PaymentHistory.query.filter(
        PaymentHistory.created_at >= thirty_days_ago,
        PaymentHistory.status == 'succeeded'
    ).all()
    monthly_revenue = sum(p.amount for p in recent_payments)

    all_time_payments = PaymentHistory.query.filter_by(status='succeeded').all()
    total_revenue = sum(p.amount for p in all_time_payments)

    total_devices = get_total_devices_all_users()
    total_storage = get_total_storage_all_users()

    plan_stats = {}
    for plan_key in Config.PLANS.keys():
        plan_stats[plan_key] = User.query.filter_by(plan=plan_key).count()

    recent_payments_list = PaymentHistory.query.order_by(
        PaymentHistory.created_at.desc()
    ).limit(5).all()

    return render_template('admin_dashboard.html',
        total_users=total_users,
        active_subscriptions=active_subscriptions,
        trial_users=trial_users,
        expired_users=expired_users,
        inactive_users=inactive_users,
        monthly_revenue=monthly_revenue,
        total_revenue=total_revenue,
        total_devices=total_devices,
        total_storage=total_storage,
        recent_users=recent_users,
        recent_payments_list=recent_payments_list,
        plan_stats=plan_stats
    )


@admin_bp.route('/users')
@login_required
@admin_required
def admin_users():
    """List all users with search and filters"""
    page = request.args.get('page', 1, type=int)
    per_page = 25
    search = request.args.get('s', '').strip()
    plan_filter = request.args.get('plan', '').strip()
    status_filter = request.args.get('status', '').strip()
    active_filter = request.args.get('active', '')

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
    if plan_filter:
        query = query.filter_by(plan=plan_filter)
    if status_filter:
        query = query.filter_by(subscription_status=status_filter)
    if active_filter == '1':
        query = query.filter_by(is_active=True)
    elif active_filter == '0':
        query = query.filter_by(is_active=False)
    users = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    from config import Config
    return render_template('admin_users.html', users=users, search=search,
        plan_filter=plan_filter, status_filter=status_filter, active_filter=active_filter, config=Config)


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
        
        trial_days = load_admin_settings().get('default_trial_days', 7)
        user = User(
            username=username, email=email, company_name=company_name,
            plan=plan, is_admin=is_admin,
            subscription_status='trial' if plan == 'free' else 'active',
            trial_ends_at=datetime.utcnow() + timedelta(days=trial_days) if plan == 'free' else None
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


@admin_bp.route('/users/<int:user_id>/extend-trial', methods=['POST'])
@login_required
@admin_required
def extend_user_trial(user_id):
    """Extend user trial by N days"""
    user = User.query.get_or_404(user_id)
    try:
        days = int(request.form.get('days', 7) or 7)
        days = max(1, min(365, days))
    except (ValueError, TypeError):
        days = 7
    if user.trial_ends_at and user.trial_ends_at > datetime.utcnow():
        user.trial_ends_at = user.trial_ends_at + timedelta(days=days)
    else:
        user.trial_ends_at = datetime.utcnow() + timedelta(days=days)
    user.subscription_status = 'trial'
    db.session.commit()
    flash(f'Trial extended by {days} days for {user.username}', 'success')
    return redirect(url_for('admin.admin_user_detail', user_id=user_id))


@admin_bp.route('/users/bulk-action', methods=['POST'])
@login_required
@admin_required
def admin_users_bulk_action():
    """Bulk activate, deactivate, or change plan"""
    from config import Config
    action = request.form.get('bulk_action')
    user_ids = request.form.getlist('user_ids')
    if not user_ids or not action:
        flash('No users selected or invalid action', 'error')
        return redirect(url_for('admin.admin_users'))

    ids = [int(i) for i in user_ids if str(i).isdigit()]
    users = User.query.filter(User.id.in_(ids)).all()
    count = 0
    for user in users:
        if user.id == current_user.id and action in ('deactivate',):
            continue
        if action == 'activate':
            user.is_active = True
            count += 1
        elif action == 'deactivate':
            user.is_active = False
            count += 1
        elif action == 'plan':
            new_plan = request.form.get('bulk_plan')
            if new_plan in Config.PLANS:
                user.plan = new_plan
                user.subscription_status = 'active'
                count += 1

    db.session.commit()
    flash(f'Bulk action completed: {count} user(s) updated', 'success')
    return redirect(url_for('admin.admin_users'))


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


@admin_bp.route('/activity')
@login_required
@admin_required
def admin_activity():
    """System-wide activity log"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    user_filter = request.args.get('user_id', type=int)
    event_filter = request.args.get('event_type', '').strip()

    query = ActivityLog.query
    if user_filter:
        query = query.filter_by(user_id=user_filter)
    if event_filter:
        query = query.filter(ActivityLog.event_type.ilike(f'%{event_filter}%'))
    activities = query.order_by(ActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('admin_activity.html', activities=activities, users=User.query.order_by(User.username).all(), user_filter=user_filter, event_filter=event_filter)


@admin_bp.route('/analytics')
@login_required
@admin_required
def admin_analytics():
    """System-wide analytics"""
    from config import Config
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    daily_signups = db.session.query(
        db.func.date(User.created_at).label('date'),
        db.func.count(User.id).label('count')
    ).filter(User.created_at >= thirty_days_ago)\
     .group_by(db.func.date(User.created_at))\
     .all()

    daily_revenue = db.session.query(
        db.func.date(PaymentHistory.created_at).label('date'),
        db.func.sum(PaymentHistory.amount).label('total')
    ).filter(
        PaymentHistory.created_at >= thirty_days_ago,
        PaymentHistory.status == 'succeeded'
    ).group_by(db.func.date(PaymentHistory.created_at))\
     .all()

    total_revenue = db.session.query(db.func.sum(PaymentHistory.amount)).filter(
        PaymentHistory.status == 'succeeded'
    ).scalar() or 0

    revenue_by_plan = db.session.query(
        PaymentHistory.plan,
        db.func.sum(PaymentHistory.amount).label('total'),
        db.func.count(PaymentHistory.id).label('count')
    ).filter(PaymentHistory.status == 'succeeded')\
     .group_by(PaymentHistory.plan).all()

    return render_template('admin_analytics.html',
        daily_signups=daily_signups,
        daily_revenue=daily_revenue,
        total_revenue=total_revenue,
        revenue_by_plan=revenue_by_plan
    )


@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    """Admin settings page"""
    if request.method == 'POST':
        settings = load_admin_settings()
        if request.form.get('form_section') == 'payoneer':
            settings['payoneer_email'] = request.form.get('payoneer_email', '').strip()
            settings['payoneer_instructions'] = request.form.get('payoneer_instructions', '').strip()
            flash('Payoneer settings saved.', 'success')
        else:
            settings['site_name'] = request.form.get('site_name', 'Digital Signage').strip() or 'Digital Signage'
            settings['support_email'] = request.form.get('support_email', '').strip()
            try:
                trial_days = int(request.form.get('default_trial_days', 7) or 7)
                settings['default_trial_days'] = max(1, min(365, trial_days))
            except (ValueError, TypeError):
                settings['default_trial_days'] = 7
            settings['maintenance_mode'] = request.form.get('maintenance_mode') == 'on'
            flash('Settings saved successfully', 'success')
        save_admin_settings(settings)
        return redirect(url_for('admin.admin_settings'))
    return render_template('admin_settings.html', settings=load_admin_settings())


@admin_bp.route('/payments')
@login_required
@admin_required
def admin_payments():
    """View all payments with filters and export"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    status_filter = request.args.get('status', '').strip()

    query = PaymentHistory.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    payments = query.order_by(PaymentHistory.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    total_succeeded = db.session.query(db.func.sum(PaymentHistory.amount)).filter(
        PaymentHistory.status == 'succeeded'
    ).scalar() or 0

    if request.args.get('export') == 'csv':
        from flask import Response
        export_query = PaymentHistory.query
        if status_filter:
            export_query = export_query.filter_by(status=status_filter)
        all_payments = export_query.order_by(PaymentHistory.created_at.desc()).limit(5000).all()
        csv_lines = ['ID,User,Amount,Plan,Status,Date']
        for p in all_payments:
            user_name = p.user.username if p.user else str(p.user_id)
            row = [_csv_escape(p.id), _csv_escape(user_name), _csv_escape(p.amount),
                   _csv_escape(p.plan), _csv_escape(p.status), _csv_escape(p.created_at)]
            csv_lines.append(','.join(row))
        return Response('\n'.join(csv_lines), mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=payments.csv'})

    return render_template('admin_payments.html',
        payments=payments,
        total_succeeded=total_succeeded,
        status_filter=status_filter
    )


@admin_bp.route('/users/export')
@login_required
@admin_required
def admin_users_export():
    """Export users as CSV"""
    from flask import Response
    users = User.query.order_by(User.created_at.desc()).all()
    csv_lines = ['ID,Username,Email,Company,Plan,Status,Connection Code,Created']
    for u in users:
        row = [_csv_escape(u.id), _csv_escape(u.username), _csv_escape(u.email),
               _csv_escape(u.company_name), _csv_escape(u.plan), _csv_escape(u.subscription_status),
               _csv_escape(u.connection_code), _csv_escape(u.created_at)]
        csv_lines.append(','.join(row))
    return Response('\n'.join(csv_lines), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=users.csv'})
