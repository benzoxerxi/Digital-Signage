# 📱 Android APK Configuration for Multi-Tenant SaaS

## How the New System Works

In the old system:
- APK connected directly to `/api/playback/state`
- No authentication needed
- All devices shared the same content

In the new multi-tenant system:
- Each customer has isolated data
- Authentication required
- Devices need to identify which customer they belong to

## 🔧 Two Solutions

### Solution 1: Device API Key (Recommended)

Add API key authentication for devices so they can connect without login.

### Solution 2: Public Endpoint (Quick Fix)

Make a special endpoint that doesn't require login for backward compatibility.

---

## Quick Fix: Public Device Endpoint

I'll create a special endpoint that your existing APK can use.

### How it works:

**Old APK calls:**
```
http://your-server.com/api/playback/state?device_id=DEVICE123
```

**New endpoint:**
```
http://your-server.com/api/public/playback/state?device_id=DEVICE123&user_id=USER_ID
```

The `user_id` identifies which customer the device belongs to.

---

## Configuration Steps

### Step 1: Get Your User ID

1. Login to dashboard
2. Go to Account page
3. Look at URL or check browser console
4. Run in console: `console.log(current_user_id)` (we'll add this)

Or, as admin:
1. Login as admin
2. Go to Admin Dashboard
3. Find the customer
4. Note their User ID (number like 1, 2, 3)

### Step 2: Configure APK

In your Android app settings, set the server URL to:

```
http://YOUR_SERVER_IP:5000/api/public/playback/state?user_id=1
```

Replace:
- `YOUR_SERVER_IP` with your computer's IP address
- `user_id=1` with the actual user ID (admin is usually 1)

### Step 3: Test Connection

Test the URL in browser:
```
http://localhost:5000/api/public/playback/state?device_id=test123&user_id=1
```

You should get JSON response with video info.

---

## Better Solution: API Keys (For Production)

For production, use API keys instead of user IDs:

**APK calls:**
```
http://your-server.com/api/device/playback?device_id=DEVICE123
Authorization: Bearer YOUR_API_KEY
```

This is more secure and professional.

---

## What to Do Right Now

**Option A: Quick Test (Use Public Endpoint)**
1. I'll add a public endpoint for you
2. You configure APK with user_id parameter
3. Works immediately with existing APK

**Option B: Update APK (Best for Production)**
1. Update Android app to send API key
2. More secure
3. Takes more time

**Which do you prefer?**

Let me know and I'll implement it for you!
