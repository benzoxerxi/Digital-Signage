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
        # Avoid "SSL SYSCALL error: EOF detected" after redeploy or idle: ping before use, recycle connections
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,   # test connection before use; discard if dead
            'pool_recycle': 300,    # recycle connections every 5 min (under typical server idle timeout)
        }
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///signage.db'
        SQLALCHEMY_ENGINE_OPTIONS = {}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # File upload and tenant data (devices, playlists, etc.)
    # Set DATA_DIR to a persistent disk path (e.g. Render: /opt/render/project/data) so offline devices and data survive redeploys.
    _data_dir = os.environ.get('DATA_DIR', '').strip()
    UPLOAD_FOLDER = os.path.join(_data_dir, 'tenants') if _data_dir else 'data/tenants'
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size
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

    # Google Drive (OAuth: users connect their own Drive)
    GOOGLE_DRIVE_CLIENT_ID = os.environ.get('GOOGLE_DRIVE_CLIENT_ID', '')
    GOOGLE_DRIVE_CLIENT_SECRET = os.environ.get('GOOGLE_DRIVE_CLIENT_SECRET', '')
    GOOGLE_DRIVE_REDIRECT_URI = os.environ.get('GOOGLE_DRIVE_REDIRECT_URI', '')  # e.g. https://yourapp.com/api/auth/google/drive/callback

    # Stripe (add your keys later)
    STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY') or 'pk_test_...'
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY') or 'sk_test_...'
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET') or 'whsec_...'
    
    # Subscription Plans (Trial + $10 paid only)
    PLANS = {
        'free': {
            'name': 'Trial',
            'price': 0,
            'price_id': None,
            'max_displays': -1,   # Unlimited
            'max_storage_gb': 50, # Server storage; content may be purged periodically
            'trial_days': 7,
            'features': [
                '7 days free',
                'Unlimited displays',
                'No support'
            ]
        },
        'paid': {
            'name': '$10 Plan',
            'price': 10,
            'price_id': os.environ.get('STRIPE_PRICE_PAID') or 'price_paid',  # Set in .env or Stripe Dashboard
            'max_displays': -1,   # Unlimited
            'max_storage_gb': 50,
            'features': [
                'Unlimited displays',
                'Support on email'
            ]
        }
    }
