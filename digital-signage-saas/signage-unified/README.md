# Signage Unified

A single app that combines the digital signage player with built-in watchdog. The watchdog runs inside the same app, so it can restart the player from the background without Android's cross-app restrictions.

## Features

- **Signage player** – Same functionality as the original android-app (video playback, connection code, etc.)
- **Built-in watchdog** – Monitors MainActivity and restarts it when closed
- **Runs in background** – No cross-app activity start; launches own activity from own service
- **Boot auto-start** – Starts automatically ~27 seconds after device boot

## Build

Open in Android Studio or run:
```bash
./gradlew assembleDebug
```

## Setup

1. Install the APK on your signage device
2. Open the app once and enter your 9-digit connection code
3. **Grant Usage Access** (Settings → Apps → Signage Unified → enable usage access) for process detection
4. **Disable battery optimization** when prompted
5. **Allow notifications** (Android 13+) – needed for full-screen intent to show the player
6. The watchdog starts automatically; it will restart the player if it closes
7. If the player doesn't appear after reboot, **tap the "Tap to show player" notification**

## How It Works

- When you open the app, MainActivity starts the WatchdogService
- The service runs in the foreground with a notification
- Every 15 seconds it checks if MainActivity was recently used (via UsageStatsManager)
- If not, it launches MainActivity to the **front** (same app → no background restriction)
- On boot, BootReceiver schedules the service to start after 10 seconds, then the player appears on screen immediately
