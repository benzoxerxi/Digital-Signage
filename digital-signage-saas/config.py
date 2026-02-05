"""
Configuration settings for Digital Signage SaaS
"""
import os
from datetime import timedelta

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database: use DATABASE_URL in production so users/data persist across deploys (e.g. Render Postgres)
    _database_url = os.environ.get('DATABASE_URL')
    if _database_url:
        # Some hosts (e.g. Render) give postgres://; SQLAlchemy expects postgresql://
        if _database_url.startswith('postgres://'):
            _database_url = 'postgresql://' + _database_url[9:]
        SQLALCHEMY_DATABASE_URI = _database_url
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///signage.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # File upload
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size
    UPLOAD_FOLDER = 'data/tenants'
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov', 'webm', 'jpg', 'jpeg', 'png', 'gif'}
    
    # Device settings
    DEVICE_TIMEOUT = 15  # seconds
    
    # Email (for verification, etc.)
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME

    # Stripe (add your keys later)
    STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY') or 'pk_test_...'
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY') or 'sk_test_...'
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET') or 'whsec_...'
    
    # Subscription Plans
    PLANS = {
        'free': {
            'name': 'Free Trial',
            'price': 0,
            'price_id': None,  # No Stripe price for free
            'max_displays': 2,
            'max_storage_gb': 5,
            'trial_days': 7,
            'features': [
                '2 displays',
                '5GB storage',
                'Basic scheduling',
                '7-day trial'
            ]
        },
        'starter': {
            'name': 'Starter',
            'price': 29,
            'price_id': 'price_starter',  # Replace with real Stripe price ID
            'max_displays': 5,
            'max_storage_gb': 20,
            'features': [
                '5 displays',
                '20GB storage',
                'Advanced scheduling',
                'Email support',
                'Device groups'
            ]
        },
        'professional': {
            'name': 'Professional',
            'price': 79,
            'price_id': 'price_professional',
            'max_displays': 15,
            'max_storage_gb': 100,
            'features': [
                '15 displays',
                '100GB storage',
                'All scheduling features',
                'Priority support',
                'Analytics dashboard',
                'API access'
            ]
        },
        'enterprise': {
            'name': 'Enterprise',
            'price': 199,
            'price_id': 'price_enterprise',
            'max_displays': -1,  # Unlimited
            'max_storage_gb': 500,
            'features': [
                'Unlimited displays',
                '500GB storage',
                'White-label option',
                'Dedicated support',
                'Custom integrations',
                'SLA guarantee'
            ]
        }
    }
