# 🚀 Deployment Guide for Complete Beginners

This guide will walk you through deploying your Digital Signage SaaS platform from scratch. **No prior experience required!**

## ⚠️ Keep users and data across deploys

On **Render**, **Heroku**, and similar platforms, the server filesystem is **ephemeral**: every new deploy gets a fresh disk. If you use the default SQLite database, **all users and data are lost on each deploy**.

**Fix:** Use a **persistent database** and set `DATABASE_URL`:

- **Render:** In the dashboard, add a **PostgreSQL** service, then in your Web Service add the Postgres instance as a "Database" dependency. Render will set `DATABASE_URL` automatically so users and data survive deploys.
- **Heroku:** Add the Heroku Postgres add-on; `DATABASE_URL` is set automatically.
- **Other hosts:** Create a PostgreSQL (or compatible) database and set the `DATABASE_URL` environment variable to its connection URL (e.g. `postgresql://user:password@host/dbname`).

## Part 1: Local Testing (Do This First!)

### Step 1: Install Python

**Windows:**
1. Go to https://www.python.org/downloads/
2. Download Python 3.11 (latest stable version)
3. Run installer, **CHECK** "Add Python to PATH"
4. Click "Install Now"

**Mac:**
```bash
# Install Homebrew first (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

### Step 2: Get the Code

1. Download the project folder
2. Extract it
3. Open Terminal/Command Prompt
4. Navigate to project:
```bash
cd path/to/digital-signage-saas
```

### Step 3: Setup & Run

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Step 4: Test It!

1. Open browser: http://localhost:5000
2. Click "Get Started" to register
3. Create account
4. Login
5. Upload a test video
6. Congratulations! It works! 🎉

---

## Part 2: Buy Hosting & Domain

### Recommended: DigitalOcean ($12/month)

#### Why DigitalOcean?
- Beginner-friendly
- Good documentation
- Cheap ($12/month)
- One-click apps

#### Sign Up

1. Go to https://www.digitalocean.com
2. Click "Sign Up"
3. Create account (use GitHub or Email)
4. Add payment method (credit card)
5. **Get $200 credit** (usually for new users)

### Buy a Domain (Optional but Recommended)

**Recommended: Namecheap**
1. Go to https://www.namecheap.com
2. Search for your domain (e.g., `mysignage.com`)
3. Buy it (~$10-15/year)
4. We'll connect it later

---

## Part 3: Deploy to DigitalOcean

### Method A: App Platform (Easiest - Recommended for Beginners)

#### Step 1: Create App

1. Login to DigitalOcean
2. Click "Create" → "Apps"
3. Choose "GitHub" (or upload code)
4. Select repository
5. Click "Next"

#### Step 2: Configure

**Resource:**
- Type: Web Service
- Name: digital-signage
- Build Command: `pip install -r requirements.txt`
- Run Command: `gunicorn -w 4 -b 0.0.0.0:8080 app:app`

**Environment Variables:**
Add these in "Environment Variables" section:
```
SECRET_KEY=your-random-secret-key-here
DATABASE_URL=postgresql://user:pass@host/db
```

#### Step 3: Choose Plan

- Basic: $12/month (1GB RAM) - **Choose This**
- Click "Launch App"
- Wait 5-10 minutes for deployment

#### Step 4: Get Your URL

After deployment:
- You'll get a URL like: `https://your-app-name.ondigitalocean.app`
- Visit it! Your site is LIVE! 🎉

---

### Method B: Droplet (More Control)

#### Step 1: Create Droplet

1. DigitalOcean Dashboard
2. Click "Create" → "Droplets"
3. Choose:
   - **Image**: Ubuntu 22.04 LTS
   - **Plan**: Basic $12/month (2GB RAM)
   - **Datacenter**: Closest to you
   - **Authentication**: Password (or SSH key if you know how)
4. Click "Create Droplet"
5. Wait 2 minutes

#### Step 2: Connect to Server

**Windows (use PuTTY):**
1. Download PuTTY: https://www.putty.org/
2. Enter your droplet IP
3. Click "Open"
4. Login as `root`
5. Enter password (sent to your email)

**Mac/Linux:**
```bash
ssh root@YOUR_DROPLET_IP
# Enter password when prompted
```

#### Step 3: Install Everything

Copy and paste this **entire block** (it's automated!):

```bash
#!/bin/bash

echo "🚀 Installing Digital Signage SaaS..."

# Update system
apt update && apt upgrade -y

# Install dependencies
apt install python3 python3-pip python3-venv nginx supervisor git postgresql postgresql-contrib -y

# Create app directory
mkdir -p /var/www/signage
cd /var/www/signage

# Clone your code (if using GitHub)
# git clone YOUR_REPO_URL .
# OR manually upload files using scp or FileZilla

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt gunicorn psycopg2-binary

# Setup PostgreSQL
sudo -u postgres psql << EOF
CREATE DATABASE signage;
CREATE USER signageuser WITH PASSWORD 'CHANGE_THIS_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE signage TO signageuser;
\q
EOF

# Create .env file
cat > .env << 'ENVFILE'
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=postgresql://signageuser:CHANGE_THIS_PASSWORD@localhost/signage
STRIPE_PUBLIC_KEY=pk_test_your_key_here
STRIPE_SECRET_KEY=sk_test_your_key_here
ENVFILE

# Create supervisor config
cat > /etc/supervisor/conf.d/signage.conf << 'SUPCONF'
[program:signage]
directory=/var/www/signage
command=/var/www/signage/venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 app:app
user=www-data
autostart=true
autorestart=true
stderr_logfile=/var/log/signage/err.log
stdout_logfile=/var/log/signage/out.log
SUPCONF

# Create log directory
mkdir -p /var/log/signage
chown www-data:www-data /var/log/signage

# Configure Nginx
cat > /etc/nginx/sites-available/signage << 'NGINX'
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static {
        alias /var/www/signage/static;
    }

    client_max_body_size 500M;
}
NGINX

# Enable site
ln -s /etc/nginx/sites-available/signage /etc/nginx/sites-enabled/
rm /etc/nginx/sites-enabled/default

# Start services
supervisorctl reread
supervisorctl update
systemctl restart nginx

echo "✅ Installation complete!"
echo "Your site is live at: http://YOUR_DROPLET_IP"
```

#### Step 4: Upload Your Code

If you didn't use Git, upload files:

**Option 1: FileZilla (Easy GUI)**
1. Download FileZilla: https://filezilla-project.org/
2. Connect to: `sftp://YOUR_IP`
3. Username: `root`
4. Password: your droplet password
5. Upload all files to `/var/www/signage`

**Option 2: Command Line (scp)**
```bash
# From your computer
scp -r digital-signage-saas/* root@YOUR_IP:/var/www/signage/
```

#### Step 5: Start Application

```bash
# On server
cd /var/www/signage
source venv/bin/activate
python app.py  # Test it works
# Press Ctrl+C

# Start with supervisor
supervisorctl restart signage
supervisorctl status signage
```

#### Step 6: Access Your Site

Open browser:
```
http://YOUR_DROPLET_IP
```

You should see your site! 🎉

---

## Part 4: Connect Your Domain

### Step 1: Point Domain to Server

In Namecheap (or your domain provider):

1. Go to Domain List
2. Click "Manage" on your domain
3. Go to "Advanced DNS"
4. Add/Edit records:

```
Type: A Record
Host: @
Value: YOUR_DROPLET_IP
TTL: Automatic

Type: A Record
Host: www
Value: YOUR_DROPLET_IP
TTL: Automatic
```

5. Save
6. Wait 5-60 minutes for DNS propagation

### Step 2: Update Nginx

On your server:
```bash
nano /etc/nginx/sites-available/signage
```

Change:
```
server_name YOUR_DOMAIN_OR_IP;
```

To:
```
server_name yourdomain.com www.yourdomain.com;
```

Save and restart:
```bash
systemctl restart nginx
```

### Step 3: Add SSL (HTTPS)

```bash
# Install Certbot
apt install certbot python3-certbot-nginx -y

# Get certificate
certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Follow prompts, enter email, agree to terms
# Choose: Redirect HTTP to HTTPS
```

Done! Your site now has HTTPS! 🔒

---

## Part 5: Setup Stripe (Payments)

### Step 1: Create Stripe Account

1. Go to https://stripe.com
2. Sign up
3. Activate account (may need business info)

### Step 2: Get Test Keys

1. Dashboard → Developers → API Keys
2. Copy:
   - **Publishable key** (starts with `pk_test_`)
   - **Secret key** (starts with `sk_test_`)

### Step 3: Add to Your App

On server:
```bash
nano /var/www/signage/.env
```

Update:
```
STRIPE_PUBLIC_KEY=pk_test_YOUR_KEY
STRIPE_SECRET_KEY=sk_test_YOUR_KEY
```

Save and restart:
```bash
supervisorctl restart signage
```

### Step 4: Create Products

In Stripe Dashboard:
1. Products → Create Product
2. Create 3 products:
   - **Starter**: $29/month recurring
   - **Professional**: $79/month recurring
   - **Enterprise**: $199/month recurring
3. Copy each Price ID (starts with `price_`)

### Step 5: Update config.py

On server:
```bash
nano /var/www/signage/config.py
```

Update the price IDs:
```python
'starter': {
    'price_id': 'price_YOUR_STARTER_PRICE_ID',
    ...
},
```

Restart:
```bash
supervisorctl restart signage
```

### Step 6: Test Payment

1. Go to your site
2. Sign up for paid plan
3. Use test card: `4242 4242 4242 4242`
4. Any future date, any CVC
5. Check Stripe Dashboard → Payments

---

## Part 6: Maintenance & Monitoring

### Daily Checks

```bash
# SSH to server
ssh root@YOUR_IP

# Check if app is running
supervisorctl status signage

# View logs
tail -f /var/log/signage/out.log
tail -f /var/log/signage/err.log

# Check disk space
df -h
```

### Backup Database

```bash
# Run daily
pg_dump signage > backup_$(date +%Y%m%d).sql

# Download to your computer
scp root@YOUR_IP:backup_*.sql .
```

### Update Application

```bash
cd /var/www/signage
git pull  # if using git
# OR upload new files

supervisorctl restart signage
```

---

## 🆘 Troubleshooting

### Site Not Loading

1. Check nginx: `systemctl status nginx`
2. Check app: `supervisorctl status signage`
3. View logs: `tail -f /var/log/signage/err.log`

### Database Errors

```bash
# Check PostgreSQL
systemctl status postgresql

# Test connection
sudo -u postgres psql signage
\q
```

### 502 Bad Gateway

```bash
# App crashed, check logs
tail -f /var/log/signage/err.log

# Restart
supervisorctl restart signage
```

### Can't Upload Videos

```bash
# Check disk space
df -h

# Increase nginx upload limit
nano /etc/nginx/sites-available/signage
# Change client_max_body_size

systemctl restart nginx
```

---

## 🎉 You're Done!

Your Digital Signage SaaS is:
- ✅ Running on production server
- ✅ Accessible via your domain
- ✅ Secured with HTTPS
- ✅ Accepting payments
- ✅ Ready for customers!

### Next Steps:

1. Test everything thoroughly
2. Get your first customer
3. Make money! 💰

### Need Help?

- DigitalOcean Community: https://www.digitalocean.com/community
- Python Documentation: https://docs.python.org/
- Flask Documentation: https://flask.palletsprojects.com/
- Stripe Documentation: https://stripe.com/docs

**Good luck with your business! 🚀**
