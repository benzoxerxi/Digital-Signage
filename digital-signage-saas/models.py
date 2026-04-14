"""
Database models for Digital Signage SaaS
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
import bcrypt

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User/Customer account"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Account info
    company_name = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    
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
