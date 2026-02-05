"""
Main routes - Landing page, Pricing, Dashboard, Subscriptions
"""
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
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
    from models import PaymentHistory, db
    
    current_user.ensure_connection_code()
    db.session.commit()
    
    payments = PaymentHistory.query.filter_by(user_id=current_user.id)\
        .order_by(PaymentHistory.created_at.desc()).limit(10).all()
    
    return render_template('account.html', user=current_user, payments=payments, plans=Config.PLANS)


@main_bp.route('/subscriptions')
@login_required
def subscriptions():
    """Subscriptions page - view current plan and activate/upgrade via payment"""
    return render_template('subscriptions.html', user=current_user, plans=Config.PLANS)


@main_bp.route('/subscriptions/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    """Create Stripe Checkout Session for the selected plan; return checkout URL."""
    import stripe
    from models import db

    data = request.get_json(silent=True) or {}
    plan_key = (data.get('plan') or request.form.get('plan') or '').strip().lower()
    if not plan_key or plan_key not in Config.PLANS:
        return jsonify({'error': 'Invalid plan'}), 400
    if plan_key == 'free':
        return jsonify({'error': 'Free plan does not require payment'}), 400

    plan_config = Config.PLANS[plan_key]
    price_id = plan_config.get('price_id')
    price = plan_config.get('price', 0)

    # If Stripe is not configured, allow manual activation for testing (optional)
    stripe_key = Config.STRIPE_SECRET_KEY
    if not stripe_key or stripe_key.startswith('sk_test_') and stripe_key.endswith('...'):
        # No real Stripe key: optionally activate plan for demo (e.g. from admin or same-origin)
        # For production, remove this block and require Stripe.
        return jsonify({
            'error': 'Payments not configured',
            'message': 'Set STRIPE_SECRET_KEY and STRIPE_PUBLIC_KEY in .env to enable payments. Contact support to activate a plan.'
        }), 503

    stripe.api_key = stripe_key
    try:
        customer_id = current_user.stripe_customer_id
        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                metadata={'user_id': str(current_user.id)}
            )
            customer_id = customer.id
            current_user.stripe_customer_id = customer_id
            db.session.commit()

        base = request.host_url.rstrip('/')
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': int(price * 100),
                    'product_data': {
                        'name': plan_config['name'],
                        'description': f"Digital Signage - {plan_config['name']} plan",
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{base}{url_for("main.subscription_success")}?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{base}{url_for("main.subscription_cancel")}',
            client_reference_id=str(current_user.id),
            metadata={'plan': plan_key},
        )
        return jsonify({'url': session.url})
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400


@main_bp.route('/subscriptions/success')
@login_required
def subscription_success():
    """Handle successful payment: verify session and activate subscription."""
    import stripe
    from models import User, PaymentHistory, db

    session_id = request.args.get('session_id')
    if not session_id:
        flash('No session ID received.', 'error')
        return redirect(url_for('main.subscriptions'))

    stripe_key = Config.STRIPE_SECRET_KEY
    if not stripe_key or stripe_key.startswith('sk_test_') and stripe_key.endswith('...'):
        flash('Payments not configured. Contact support to activate your plan.', 'info')
        return redirect(url_for('main.subscriptions'))

    stripe.api_key = stripe_key
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status != 'paid':
            flash('Payment not completed.', 'error')
            return redirect(url_for('main.subscriptions'))
        user_id = int(session.client_reference_id or 0)
        plan_key = (session.metadata or {}).get('plan') or 'starter'
        if user_id != current_user.id:
            flash('Invalid session.', 'error')
            return redirect(url_for('main.subscriptions'))

        user = User.query.get(user_id)
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('main.subscriptions'))

        plan_config = Config.PLANS.get(plan_key, Config.PLANS['starter'])
        user.plan = plan_key
        user.subscription_status = 'active'
        user.stripe_subscription_id = session_id
        db.session.add(user)
        db.session.add(PaymentHistory(
            user_id=user.id,
            amount=plan_config.get('price', 0),
            currency='USD',
            status='succeeded',
            stripe_payment_id=session.payment_intent or session_id,
            plan=plan_key,
        ))
        db.session.commit()
        flash(f'Payment successful! Your {plan_config["name"]} plan is now active.', 'success')
    except Exception as e:
        flash(f'Could not activate subscription: {str(e)}', 'error')
    return redirect(url_for('main.subscriptions'))


@main_bp.route('/subscriptions/cancel')
@login_required
def subscription_cancel():
    """User cancelled checkout."""
    flash('Checkout was cancelled. You can subscribe anytime from this page.', 'info')
    return redirect(url_for('main.subscriptions'))
