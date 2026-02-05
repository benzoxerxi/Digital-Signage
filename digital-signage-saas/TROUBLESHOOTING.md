# 🔧 Troubleshooting Guide

## Windows Issues

### Issue 1: "Could not open requirements.txt"

**Solution:**
Use `start.bat` instead of `run.bat`:
```cmd
start.bat
```

Or install dependencies manually:
```cmd
python -m venv venv
venv\Scripts\activate
pip install Flask Flask-CORS Flask-Login Flask-SQLAlchemy Werkzeug stripe python-dotenv bcrypt
python app.py
```

### Issue 2: "No module named 'app'"

**Solution:**
Run from the project directory:
```cmd
cd C:\path\to\digital-signage-saas
python app.py
```

Or set Python path:
```cmd
set PYTHONPATH=%CD%
python app.py
```

### Issue 3: "python is not recognized"

**Solution:**
1. Install Python from https://www.python.org/downloads/
2. During installation, CHECK "Add Python to PATH"
3. Restart terminal
4. Try again

Or use full path:
```cmd
C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe app.py
```

### Issue 4: Port 5000 already in use

**Solution:**
Kill the process using port 5000:
```cmd
netstat -ano | findstr :5000
taskkill /PID [number_from_above] /F
```

Or change the port in app.py (bottom of file):
```python
app.run(host='0.0.0.0', port=5001, debug=True)
```

### Issue 5: Database errors / locked

**Solution:**
1. Stop all Python processes
2. Delete `signage.db` (you'll lose data)
3. Restart the app

```cmd
taskkill /IM python.exe /F
del signage.db
python app.py
```

### Issue 6: Can't access from other devices on network

**Solution:**
1. Find your computer's IP address:
```cmd
ipconfig
```
Look for "IPv4 Address" (e.g., 192.168.1.100)

2. On other device, go to:
```
http://YOUR_IP_ADDRESS:5000
```

3. Check Windows Firewall:
   - Windows Security → Firewall → Allow an app
   - Add Python to allowed apps

### Issue 7: Virtual environment activation fails

**Solution:**
Enable script execution:
```cmd
powershell -Command "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser"
```

Or skip virtual environment:
```cmd
pip install Flask Flask-CORS Flask-Login Flask-SQLAlchemy Werkzeug stripe python-dotenv bcrypt
python app.py
```

---

## Mac/Linux Issues

### Issue 1: Permission denied on run.sh

**Solution:**
```bash
chmod +x run.sh
./run.sh
```

### Issue 2: Python not found

**Solution:**
Use `python3` instead:
```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
python3 app.py
```

### Issue 3: Port 5000 already in use

**Solution:**
```bash
# Find and kill process
lsof -ti:5000 | xargs kill -9

# Or change port in app.py
```

---

## Application Issues

### Issue 1: Can't login - "Invalid username or password"

**Default credentials:**
- Username: `admin`
- Password: `admin123`

If still doesn't work:
1. Stop the app
2. Delete `signage.db`
3. Restart - new admin user will be created

### Issue 2: Can't upload videos

**Check:**
1. File size limit (default 500MB)
2. Allowed formats: mp4, avi, mkv, mov, webm, jpg, jpeg, png, gif
3. Disk space: Need at least 1GB free

### Issue 3: Page not loading / white screen

**Solution:**
1. Check console for errors
2. Press Ctrl+Shift+I (Chrome DevTools)
3. Look for errors in Console tab
4. Check Network tab for failed requests

### Issue 4: "Subscription expired" after signup

**This is normal!** 
- Free trial users get 7 days
- To fix: Login as admin, go to Admin Dashboard
- Change user's plan and subscription_status

### Issue 5: Devices not showing up

**Solution:**
Devices connect by polling this URL:
```
http://YOUR_SERVER:5000/api/playback/state?device_id=TEST123
```

Test it:
1. Open that URL in browser
2. Check if you get a response
3. Device should appear in dashboard

---

## Database Issues

### Issue 1: "Table doesn't exist"

**Solution:**
Recreate database:
```python
python
>>> from app import app, db
>>> app.app_context().push()
>>> db.create_all()
>>> exit()
```

### Issue 2: "Database is locked"

**Solution:**
```cmd
# Windows
taskkill /IM python.exe /F

# Mac/Linux
pkill python

# Then restart
python app.py
```

### Issue 3: Want to reset everything

**Solution:**
```cmd
# Stop app
# Delete these files:
del signage.db
rmdir /S data

# Restart app - fresh start!
python app.py
```

---

## Deployment Issues

### Issue 1: Can't connect to server after deployment

**Check:**
1. Firewall allows port 80/443
2. Nginx is running: `systemctl status nginx`
3. App is running: `supervisorctl status signage`

### Issue 2: 502 Bad Gateway

**Solution:**
```bash
# Check app logs
tail -f /var/log/signage/err.log

# Restart app
supervisorctl restart signage

# Check if app port is open
netstat -tuln | grep 8000
```

### Issue 3: SSL certificate errors

**Solution:**
```bash
# Re-run certbot
certbot --nginx -d yourdomain.com

# Check nginx config
nginx -t

# Restart nginx
systemctl restart nginx
```

---

## Getting Help

1. **Check this file first!**
2. **Read the error message carefully**
3. **Google the exact error message**
4. **Check:**
   - README.md
   - QUICKSTART.md
   - DEPLOYMENT_GUIDE.md

5. **Common resources:**
   - Flask docs: https://flask.palletsprojects.com/
   - Stack Overflow
   - Python docs

---

## Quick Fixes Summary

**Most common issues:**

```cmd
# 1. Module not found
pip install [module_name]

# 2. Port in use
netstat -ano | findstr :5000
taskkill /PID [number] /F

# 3. Database locked
taskkill /IM python.exe /F
del signage.db
python app.py

# 4. Can't access externally
# Use your local IP: http://192.168.1.X:5000

# 5. Fresh start
del signage.db
rmdir /S data
python app.py
```

---

## Still Stuck?

1. Take a screenshot of the error
2. Note what you were trying to do
3. Check if it's a known issue above
4. Google the error message
5. Ask on Stack Overflow with tag `flask`

**Remember:** Most errors are simple and have simple fixes. Take your time and read the error messages! 🎯
