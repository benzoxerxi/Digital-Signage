# Admin Login Setup (Easiest Guide)

Use this when you need to create or reset the **admin** account so you can log in with **admin** / **admin123**.

---

## Website won’t load after redeploy?

If the site stays on “Loading…” or a blank page after a deploy on **Render**, do this:

1. **Fix the Start Command (most common)**  
   Render expects your app to listen on the port it provides (`$PORT`). If the command uses a fixed port (e.g. `8080`), Render won’t detect your app and may shut it down — you’ll see “Port scan timeout reached, no open HTTP ports detected” or “Shutting down: Master” in the logs.

   **Where to add or change the Start Command on Render:**
   - Go to [dashboard.render.com](https://dashboard.render.com) and log in.
   - Click your **Web Service** name (e.g. “digitalsignage-gits” or “DigitalSignage”) in the list.
   - In the **left sidebar**, click **Settings**.
   - Scroll to the **Build & Deploy** section. You’ll see **Build Command** and **Start Command**.
   - In **Start Command**, enter (or replace with):
     ```bash
     gunicorn -w 4 -b 0.0.0.0:$PORT app:app
     ```
   - Click **Save Changes**. Render will redeploy. Wait until the deploy is **Live**, then try opening the site again.

   If you don’t see **Settings** in the sidebar, look for **Environment** — some plans show **Start Command** there, or under a **Build & Deploy** subsection on the main service page.

2. **Wait for cold start**  
   On the free tier, the service can “spin down” when idle. The first load after that may take **30–60 seconds**. Leave the tab open and wait before refreshing.

3. **Check the logs**  
   In Render → your Web Service → **Logs**, see if the build or start failed (red errors). Fix any missing env vars or failed installs shown there.

---

## Part A: Unlink / Remove the Old Bootstrap (Start Fresh)

Do this if you want to remove the bootstrap token and start over.

### On Render

1. Go to [dashboard.render.com](https://dashboard.render.com) and log in.
2. Click your **Web Service** (the one that runs the Digital Signage app).
3. Click **Environment** in the left sidebar.
4. Find **ADMIN_BOOTSTRAP_TOKEN** in the list.
   - If it’s there: click the **trash** (or **Remove**) next to it and **Save**.
   - If you use a **Linked Environment Group**: go to **Environment Groups** in the left sidebar, open the group, remove **ADMIN_BOOTSTRAP_TOKEN**, save. Then in your Web Service → **Environment**, the variable will disappear after the next deploy.
5. Click **Manual Deploy** → **Deploy latest commit** (so the app restarts without the token).

You’ve now “unlinked” the bootstrap. The `/admin/bootstrap` URL will do nothing until you add the token again (Part B).

---

## Part B: Create Admin from the Beginning (Step by Step)

Follow these steps **in order**. Use your real app URL (e.g. `https://digitalsignage-gits.onrender.com`).

### Step 1: Create a secret token

You need a random string that only you know. Any of these works:

**Option A – Use a password generator (easiest)**  
1. Open https://passwordsgenerator.net (or search “random password generator”).  
2. Set length to about 20–30.  
3. Click **Generate** and **Copy**. That’s your token.

**Option B – Type one yourself**  
In Notepad (or any app), type a long mix of letters and numbers that’s hard to guess, e.g.  
`mySecretBootstrap2024xyz` or `adminSetupToken99AbcXyZ`.  
Copy it.

Keep it somewhere handy (e.g. Notepad). You’ll paste it in Step 2 (Render) and again in the URL in Step 4.

### Step 2: Add the token on Render

1. Go to [dashboard.render.com](https://dashboard.render.com).
2. Open your **Web Service** (the Digital Signage app).
3. Click **Environment** in the left sidebar.
4. Click **Add Environment Variable**.
5. **Key:** `ADMIN_BOOTSTRAP_TOKEN`
6. **Value:** paste the token you created (e.g. `mySecretBootstrap2024xyz`).
7. Click **Save Changes**.

**Optional – use a different admin username and password:**  
Before saving, add two more environment variables so the bootstrap creates an admin with your own login (instead of `admin` / `admin123`):

- **Key:** `ADMIN_USERNAME` → **Value:** e.g. `myadmin` (any username you want)
- **Key:** `ADMIN_PASSWORD` → **Value:** e.g. `MySecurePass123` (at least 6 characters)

Then when you run the bootstrap URL (Step 4), the admin account will be created with that username and password. Log in with those in Step 5 instead of admin / admin123.

8. Render will redeploy automatically (wait until it’s live).

### Step 3: Wait for deploy

- On the same page, wait until the deploy status is **Live** (green).
- This can take 2–5 minutes.

### Step 4: Run the bootstrap URL (create admin)

1. Open your browser.
2. In the address bar, type your app URL, then `/admin/bootstrap?token=` and then your token.

   **Example:**  
   If your app is `https://digitalsignage-gits.onrender.com` and your token is `mySecretBootstrap2024xyz`, open:

   ```
   https://digitalsignage-gits.onrender.com/admin/bootstrap?token=mySecretBootstrap2024xyz
   ```

3. Press Enter.
4. You should see a white page with something like:
   ```json
   {"success": true, "username": "admin", "password": "admin123", ...}
   ```
   (If you set `ADMIN_USERNAME` and `ADMIN_PASSWORD`, the JSON will show those instead.)
   - If you see **Invalid token**: the token in the URL doesn’t match the one in Render (check for spaces, typos).
   - If you see **Bootstrap disabled** or 404: the app didn’t get the env var; wait for deploy to finish and try again.

### Step 5: Log in

1. Go to the login page:  
   `https://your-app.onrender.com/auth/login`
2. **Username:** use the one from the bootstrap JSON (default `admin`, or the value you set in `ADMIN_USERNAME`).
3. **Password:** use the one from the bootstrap JSON (default `admin123`, or the value you set in `ADMIN_PASSWORD`).
4. Click Sign in. You should land on the admin dashboard.

### Step 6: Remove the token (for security)

1. Go back to Render → your Web Service → **Environment**.
2. Remove **ADMIN_BOOTSTRAP_TOKEN** (trash / Delete).
3. Save. The app will redeploy. After this, the bootstrap URL will no longer work (and that’s correct).

---

## Quick checklist

- [ ] Removed old **ADMIN_BOOTSTRAP_TOKEN** (Part A) if you wanted to start fresh.
- [ ] Added **ADMIN_BOOTSTRAP_TOKEN** with a secret value (Part B, Step 2).
- [ ] Waited for deploy to be **Live** (Part B, Step 3).
- [ ] Opened `/admin/bootstrap?token=YOUR_TOKEN` and saw `"success": true` (Part B, Step 4).
- [ ] Logged in at `/auth/login` with the username and password from the bootstrap response (Part B, Step 5).
- [ ] Removed **ADMIN_BOOTSTRAP_TOKEN** from Environment (Part B, Step 6).

If login still says “Invalid username or password”, open `/admin/bootstrap/check`. If it says `"admin_exists": false`, run Step 4 again with the correct token. If it says `true`, you’re typing the exact username and password from the bootstrap JSON (or the ones you set in `ADMIN_USERNAME` / `ADMIN_PASSWORD`) with no extra spaces.
