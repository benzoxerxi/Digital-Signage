# 🎬 Digital Signage SaaS Platform

A complete multi-tenant digital signage management system with subscription billing, user authentication, and enterprise-grade features.

## ✨ Features

- **Multi-Tenant Architecture** - Each customer gets isolated data
- **User Authentication** - Secure login and registration
- **Subscription Management** - Multiple pricing tiers with trials
- **Digital Signage Control** - Manage displays, playlists, schedules
- **Device Management** - Monitor and control multiple displays
- **Content Library** - Upload and organize videos/images
- **Scheduling** - Automated content scheduling
- **Analytics** - Track usage and performance
- **Admin Dashboard** - Manage all customers and system

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git (optional, for version control)

## 🚀 Quick Start (Local Development)

### 1. Download/Clone the Project

```bash
# If using git
git clone <your-repo-url>
cd digital-signage-saas

# Or just extract the ZIP file and cd into it
```

### 2. Create Virtual Environment

```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
# Copy the example env file
cp .env.example .env

# Edit .env and add your configuration
# For now, the defaults work for local testing
```

### 5. Initialize Database

```bash
python app.py
```

This will:
- Create the database (`signage.db`)
- Create all tables
- Create admin user (username: `admin`, password: `admin123`)
- Start the server on http://localhost:5000

⚠️ **IMPORTANT**: Change the admin password immediately after first login!

### 6. Access the Application

Open your browser and go to:
- **Homepage**: http://localhost:5000
- **Login**: http://localhost:5000/auth/login
- **Register**: http://localhost:5000/auth/register

**Default Admin Login:**
- Username: `admin`
- Password: `admin123` (CHANGE THIS!)

## 📁 Project Structure

```
digital-signage-saas/
├── app.py                  # Main application
├── auth.py                 # Authentication routes
├── routes_main.py          # Public pages (landing, dashboard)
├── routes_api.py           # API endpoints for signage control
├── routes_admin.py         # Admin dashboard routes
├── models.py               # Database models
├── config.py               # Configuration settings
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── .gitignore             # Git ignore rules
├── templates/             # HTML templates
│   ├── base.html
│   ├── landing.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── account.html
│   └── admin_*.html
├── static/                # Static files (CSS, JS)
│   ├── css/
│   └── js/
└── data/                  # User data (auto-created)
    └── tenants/           # Tenant-specific data
```

## 🌐 Production Deployment (DigitalOcean)

### Option 1: DigitalOcean App Platform (Easiest)

1. Create a DigitalOcean account
2. Go to App Platform
3. Connect your GitHub repo or upload code
4. Set environment variables
5. Deploy!

**Cost**: ~$12/month

### Option 2: DigitalOcean Droplet (More Control)

#### 1. Create a Droplet

- Go to DigitalOcean
- Create Droplet
- Choose: Ubuntu 22.04 LTS
- Size: Basic $12/month (2GB RAM)
- Select region closest to you
- Add SSH key or use password

#### 2. Connect to Server

```bash
ssh root@your_server_ip
```

#### 3. Install Requirements

```bash
# Update system
apt update && apt upgrade -y

# Install Python and dependencies
apt install python3 python3-pip python3-venv nginx git -y

# Install supervisor for process management
apt install supervisor -y
```

#### 4. Setup Application

```bash
# Create app directory
mkdir -p /var/www/signage
cd /var/www/signage

# Upload your code (use git or scp)
git clone <your-repo>
# OR use scp to copy files

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt gunicorn

# Create .env file
nano .env
# Add your production settings
```

#### 5. Create Supervisor Config

```bash
nano /etc/supervisor/conf.d/signage.conf
```

Add:
```ini
[program:signage]
directory=/var/www/signage
command=/var/www/signage/venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 app:app
user=www-data
autostart=true
autorestart=true
stderr_logfile=/var/log/signage/err.log
stdout_logfile=/var/log/signage/out.log
```

Create log directory:
```bash
mkdir -p /var/log/signage
chown www-data:www-data /var/log/signage
```

#### 6. Configure Nginx

```bash
nano /etc/nginx/sites-available/signage
```

Add:
```nginx
server {
    listen 80;
    server_name your_domain.com;  # or your_server_ip

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /static {
        alias /var/www/signage/static;
    }

    client_max_body_size 500M;  # For large video uploads
}
```

Enable site:
```bash
ln -s /etc/nginx/sites-available/signage /etc/nginx/sites-enabled/
nginx -t  # Test configuration
systemctl restart nginx
```

#### 7. Start Application

```bash
supervisorctl reread
supervisorctl update
supervisorctl start signage
supervisorctl status
```

#### 8. Setup SSL (Optional but Recommended)

```bash
apt install certbot python3-certbot-nginx -y
certbot --nginx -d your_domain.com
```

### Database Migration to PostgreSQL (Production)

For production, switch to PostgreSQL:

```bash
# Install PostgreSQL
apt install postgresql postgresql-contrib -y

# Create database
sudo -u postgres psql
CREATE DATABASE signage;
CREATE USER signageuser WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE signage TO signageuser;
\q

# Update .env
DATABASE_URL=postgresql://signageuser:your_secure_password@localhost/signage

# Restart app
supervisorctl restart signage
```

## 💳 Stripe Integration

### 1. Create Stripe Account

Go to https://stripe.com and create an account

### 2. Get API Keys

- Dashboard → Developers → API Keys
- Copy Publishable Key and Secret Key

### 3. Create Products & Prices

In Stripe Dashboard:
1. Products → Create Product
2. Create for each plan (Starter, Professional, Enterprise)
3. Copy the Price IDs
4. Update in `config.py`

### 4. Setup Webhook

1. Developers → Webhooks → Add Endpoint
2. URL: `https://yourdomain.com/api/stripe/webhook`
3. Events: `checkout.session.completed`, `invoice.paid`, `customer.subscription.deleted`
4. Copy webhook secret to `.env`

## 🔧 Configuration

Edit `config.py` to customize:
- Plans and pricing
- File upload limits
- Device timeout
- Features per plan

## 📊 Admin Panel

Access at: `/admin`

Default admin credentials:
- Username: `admin`
- Password: `admin123` (CHANGE THIS!)

Features:
- View all users
- Monitor subscriptions
- Track revenue
- Manage users
- System analytics

## 🐛 Troubleshooting

### Port Already in Use

```bash
# Find process using port 5000
lsof -i :5000
# Kill it
kill -9 <PID>
```

### Database Locked Error

```bash
# Stop all Python processes
pkill python
# Restart
python app.py
```

### File Upload Fails

Check:
1. `MAX_CONTENT_LENGTH` in `config.py`
2. Nginx `client_max_body_size`
3. Disk space: `df -h`

### Can't Access from Other Devices

Make sure you're using:
- `app.run(host='0.0.0.0')` in development
- Correct firewall rules in production

## 📝 Development

### Running in Debug Mode

```bash
python app.py
```

Debug mode is enabled by default in `app.py`

### Running Tests

```bash
# Install pytest
pip install pytest

# Run tests (create tests/ directory first)
pytest
```

### Database Migrations

```bash
# If using Flask-Migrate
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
```

## 🔒 Security Checklist

- [ ] Change admin password
- [ ] Generate new SECRET_KEY
- [ ] Use HTTPS in production
- [ ] Use PostgreSQL for production
- [ ] Setup firewall (ufw)
- [ ] Regular backups
- [ ] Keep dependencies updated
- [ ] Use environment variables for secrets

## 📦 Backup

### Backup Database

```bash
# SQLite
cp signage.db signage_backup_$(date +%Y%m%d).db

# PostgreSQL
pg_dump signage > backup.sql
```

### Backup User Data

```bash
tar -czf data_backup.tar.gz data/
```

## 🚀 Scaling

When you grow:

1. **Database**: Migrate to managed PostgreSQL
2. **File Storage**: Use S3/Spaces for videos
3. **Load Balancer**: Add more app servers
4. **CDN**: CloudFlare for content delivery
5. **Caching**: Add Redis

## 📞 Support

For issues:
1. Check logs: `/var/log/signage/` or console output
2. Review configuration
3. Check database connection

## 📄 License

[Your License Here]

## 🎉 Next Steps

1. ✅ Setup local development
2. ✅ Create admin account
3. ✅ Test registration & login
4. ✅ Upload test video
5. ✅ Create test playlist
6. ⬜ Setup Stripe
7. ⬜ Deploy to production
8. ⬜ Connect real displays
9. ⬜ Launch! 🚀
