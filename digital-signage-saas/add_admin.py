"""One-time script to add or reset admin user (username: admin, password: admin123)"""
import os
import sys

# Ensure we're in the project directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, User

with app.app_context():
    admin = User.query.filter_by(username='admin').first()
    if admin:
        admin.set_password('admin123')
        admin.email = 'admin@example.com'
        admin.is_admin = True
        admin.is_active = True
        admin.ensure_connection_code()
        db.session.commit()
        print('Admin user password reset.')
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
        print('Admin user created.')
    
    print('Username: admin')
    print('Password: admin123')
    print('Login at: /auth/login')
