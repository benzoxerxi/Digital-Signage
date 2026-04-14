"""
Configuration settings for Digital Signage SaaS
"""
import os
from datetime import timedelta

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///signage.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # File upload
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size
    UPLOAD_FOLDER = 'data/tenants'
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov', 'webm', 'jpg', 'jpeg', 'png', 'gif'}
    
    # Device settings
    DEVICE_TIMEOUT = 15  # seconds
    
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
