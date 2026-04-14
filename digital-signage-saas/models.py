"""
Database models for Digital Signage SaaS
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
import bcrypt
import random
import secrets

db = SQLAlchemy()

def _generate_unique_connection_code():
    """Generate a unique 9-digit connection code for APK pairing"""
    max_attempts = 100
    for _ in range(max_attempts):
        code = str(random.randint(100000000, 999999999))
        if not User.query.filter_by(connection_code=code).first():
            return code
    raise ValueError("Could not generate unique connection code")


class User(UserMixin, db.Model):
    """User/Customer account"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # 9-digit unique code for APK/server connection (each user gets their own)
    connection_code = db.Column(db.String(9), unique=True, index=True)
    
    # Account info
    company_name = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    email_verified = db.Column(db.Boolean, default=False)
    email_verify_token = db.Column(db.String(64), nullable=True)
    email_verify_expires = db.Column(db.DateTime, nullable=True)
    
    # Subscription
    plan = db.Column(db.String(50), default='free')
    trial_ends_at = db.Column(db.DateTime)
    subscription_status = db.Column(db.String(50), default='trial')  # trial, active, canceled, expired
    stripe_customer_id = db.Column(db.String(100))
    stripe_subscription_id = db.Column(db.String(100))
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        """Check if password matches"""
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def get_tenant_id(self):
        """Get unique tenant identifier"""
        return f"tenant_{self.id}"
    
    def ensure_connection_code(self):
        """Ensure user has a 9-digit connection code; generate if missing"""
        if self.connection_code:
            return self.connection_code
        self.connection_code = _generate_unique_connection_code()
        return self.connection_code

    def set_email_verify_token(self):
        """Generate and set email verification token (expires in 24h). Returns token."""
        self.email_verify_token = secrets.token_urlsafe(32)
        self.email_verify_expires = datetime.utcnow() + timedelta(hours=24)
        return self.email_verify_token
    
    @classmethod
    def get_by_connection_code(cls, code):
        """Look up user by 9-digit connection code (for APK authentication)"""
        if not code or len(code) != 9 or not code.isdigit():
            return None
        return cls.query.filter_by(connection_code=code).first()
    
    def is_trial_active(self):
        """Check if trial is still active"""
        if self.trial_ends_at and datetime.utcnow() < self.trial_ends_at:
            return True
        return False
    
    def is_subscription_active(self):
        """Check if user has active subscription"""
        if self.subscription_status == 'active':
            return True
        if self.subscription_status == 'trial' and self.is_trial_active():
            return True
        return False
    
    def get_plan_limits(self):
        """Get current plan limits"""
        from config import Config
        plan_config = Config.PLANS.get(self.plan, Config.PLANS['free'])
        return {
            'max_displays': plan_config['max_displays'],
            'max_storage_gb': plan_config['max_storage_gb'],
            'plan_name': plan_config['name']
        }
    
    def can_add_device(self, current_device_count):
        """Check if user can add more devices"""
        limits = self.get_plan_limits()
        max_displays = limits['max_displays']
        if max_displays == -1:  # Unlimited
            return True
        return current_device_count < max_displays
    
    def can_upload_content(self, current_storage_gb):
        """Check if user can upload more content"""
        limits = self.get_plan_limits()
        return current_storage_gb < limits['max_storage_gb']
    
    def __repr__(self):
        return f'<User {self.username}>'


class TenantDisplay(db.Model):
    """Persistent registry of displays per account. Survives loss of tenant devices.json (e.g. ephemeral disk);
    merged with devices.json for commands and live state. Removed only when user deletes the display."""
    __tablename__ = 'tenant_displays'
    __table_args__ = (db.UniqueConstraint('user_id', 'device_id', name='uq_tenant_display_device'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    device_id = db.Column(db.String(160), nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    first_seen_iso = db.Column(db.String(40), nullable=False)
    last_seen_iso = db.Column(db.String(40), nullable=False)
    # Hot operational state (migrated from devices.json)
    current_video = db.Column(db.String(500), nullable=True)
    command_id = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(32), nullable=False, default='idle')
    device_info_json = db.Column(db.Text, nullable=True)
    screenshot_requested = db.Column(db.Boolean, nullable=False, default=False)
    clear_cache = db.Column(db.Boolean, nullable=False, default=False)
    playback_cache_only = db.Column(db.Boolean, nullable=False, default=False)
    cache_manifest_json = db.Column(db.Text, nullable=True)
    cache_manifest_file_count = db.Column(db.Integer, nullable=True)
    cache_manifest_total_bytes = db.Column(db.BigInteger, nullable=True)
    cache_manifest_updated_at = db.Column(db.String(40), nullable=True)
    cache_delete_keys_json = db.Column(db.Text, nullable=True)
    current_video_display_name = db.Column(db.String(250), nullable=True)


class PaymentHistory(db.Model):
    """Payment transaction history"""
    __tablename__ = 'payment_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='USD')
    status = db.Column(db.String(50))  # succeeded, failed, pending
    
    stripe_payment_id = db.Column(db.String(100))
    stripe_invoice_id = db.Column(db.String(100))
    
    plan = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('payments', lazy=True))
    
    def __repr__(self):
        return f'<Payment {self.id} - ${self.amount}>'


class ActivityLog(db.Model):
    """Activity/analytics log"""
    __tablename__ = 'activity_log'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    event_type = db.Column(db.String(100), nullable=False)  # video_played, device_connected, etc.
    event_data = db.Column(db.Text)  # JSON string
    ip_address = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('activities', lazy=True))
    
    def __repr__(self):
        return f'<Activity {self.event_type}>'
