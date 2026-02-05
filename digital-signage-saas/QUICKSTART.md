# 🚀 QUICK START - Get Running in 5 Minutes!

## For Windows Users

1. **Download Python** (if not installed)
   - Go to: https://www.python.org/downloads/
   - Download Python 3.11
   - Install (CHECK "Add Python to PATH")

2. **Run the App**
   - Double-click `run.bat`
   - Wait for installation
   - Browser will show the site!

3. **Access**
   - Open browser: http://localhost:5000
   - Login: `admin` / `admin123`

That's it! 🎉

---

## For Mac/Linux Users

1. **Open Terminal**

2. **Navigate to project**
   ```bash
   cd /path/to/digital-signage-saas
   ```

3. **Run startup script**
   ```bash
   ./run.sh
   ```
   
   If permission denied:
   ```bash
   chmod +x run.sh
   ./run.sh
   ```

4. **Access**
   - Open browser: http://localhost:5000
   - Login: `admin` / `admin123`

That's it! 🎉

---

## 🎯 What to Do Next

### 1. Test the System (5 minutes)

**Create a Test Account:**
1. Click "Get Started" or "Sign Up"
2. Fill in:
   - Username: `testuser`
   - Email: `test@example.com`
   - Password: anything (6+ chars)
   - Plan: Professional
3. Click "Create Account"
4. You're logged in! ✅

**Upload a Video:**
1. Go to "Content" tab
2. Click upload area or drag video
3. Wait for upload
4. Video appears in library ✅

**Test Device Connection:**
1. Go to "Devices" tab
2. Open new tab: http://localhost:5000/api/playback/state?device_id=test123
3. Go back to dashboard
4. Refresh - you'll see new device! ✅

**Play Video:**
1. Select device (click on it)
2. Go to "Content" tab  
3. Click "Play" on a video
4. Device gets command! ✅

### 2. Understand the System (10 minutes)

**User Roles:**
- **Admin** (`admin`/`admin123`) - Manages everything
- **Customers** - Your paying users

**Key Features:**
- **Multi-tenant** - Each customer has isolated data
- **Subscriptions** - Free trial → Paid plans
- **Devices** - Connect unlimited displays
- **Content** - Videos and images
- **Scheduling** - Auto-play at specific times
- **Groups** - Organize devices
- **Analytics** - Track usage

**File Structure:**
```
digital-signage-saas/
├── app.py              ← Main application
├── config.py           ← Settings (edit plans here)
├── models.py           ← Database structure
├── auth.py             ← Login/signup
├── routes_*.py         ← Different features
├── templates/          ← HTML pages
├── static/             ← CSS, JS
└── data/              ← User data (auto-created)
    └── tenants/       ← Each user's folder
        └── tenant_1/
            ├── content/       ← Videos
            ├── devices.json   ← Devices
            ├── playlists.json
            └── ...
```

### 3. Customize (15 minutes)

**Change Plans/Pricing:**

Edit `config.py`:
```python
'starter': {
    'price': 29,  # ← Change this
    'max_displays': 5,  # ← Change this
    ...
}
```

**Change Admin Password:**
1. Login as admin
2. Go to Account
3. Change password
4. Or delete admin and create new one

**Brand Your Site:**
- Edit `templates/landing.html` - Homepage
- Edit `templates/base.html` - Logo, colors
- Put logo in `static/` folder

### 4. Deploy to Production (30 minutes)

See `DEPLOYMENT_GUIDE.md` for detailed steps.

**Quick Version:**
1. Buy DigitalOcean droplet ($12/month)
2. Upload code
3. Run deployment script
4. Done! Site is live!

---

## 🐛 Common Issues

### "Port 5000 is already in use"

**Windows:**
```cmd
netstat -ano | findstr :5000
taskkill /PID [number] /F
```

**Mac/Linux:**
```bash
lsof -ti:5000 | xargs kill -9
```

### "ModuleNotFoundError"

```bash
# Make sure venv is activated
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

pip install -r requirements.txt
```

### "Can't connect from other devices"

Make sure you use:
- Network IP (not localhost)
- Check firewall allows port 5000
- On same WiFi network

Find your IP:
- Windows: `ipconfig`
- Mac/Linux: `ifconfig`

Then access: `http://YOUR_IP:5000`

### Database locked

```bash
# Stop all Python processes
# Windows: Ctrl+C in terminal
# Mac/Linux: pkill python

# Delete database (WARNING: loses data)
# rm signage.db  # or delete signage.db file

# Restart
python app.py
```

---

## 📚 Learn More

- **Full documentation**: `README.md`
- **Deployment guide**: `DEPLOYMENT_GUIDE.md`
- **Flask tutorial**: https://flask.palletsprojects.com/
- **Python tutorial**: https://docs.python.org/3/tutorial/

---

## 🎯 Your Roadmap

- [x] Download project
- [x] Run locally
- [ ] Test all features
- [ ] Customize branding
- [ ] Setup Stripe
- [ ] Deploy to server
- [ ] Connect domain
- [ ] Add SSL
- [ ] Get first customer
- [ ] Scale! 🚀

---

## 💡 Pro Tips

1. **Always test locally first** before deploying
2. **Backup database daily** in production
3. **Use PostgreSQL** for production (not SQLite)
4. **Enable HTTPS** (free with Let's Encrypt)
5. **Start small** - get 1-2 customers before scaling
6. **Monitor logs** to catch issues early
7. **Keep it simple** - don't over-customize at first

---

## 🆘 Need Help?

**Check:**
1. This file
2. README.md
3. DEPLOYMENT_GUIDE.md
4. Console/terminal errors
5. Log files

**Still stuck?**
- Check DigitalOcean Community
- Read Flask documentation
- Google the error message
- Stack Overflow

---

## 🎉 Success Checklist

Before going live, make sure:

- [ ] Changed admin password
- [ ] Tested all features work
- [ ] Uploaded test video
- [ ] Created test schedule
- [ ] Checked mobile responsive
- [ ] Setup Stripe products
- [ ] Tested payment flow
- [ ] Have backup plan
- [ ] Domain is connected
- [ ] SSL is working
- [ ] Firewall configured
- [ ] Monitoring setup

---

**You're ready! Good luck with your SaaS business! 🚀💰**
