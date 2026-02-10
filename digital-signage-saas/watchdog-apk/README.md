# Signage Watchdog APK

A lightweight Android app that automatically starts your digital signage player on boot and monitors it, restarting if it crashes.

## Features

- **Auto-start on boot**: Starts automatically when the device boots or restarts
- **Configurable delay**: Waits 12 seconds after boot before launching your app (allows system to stabilize)
- **Crash monitoring**: Checks every 30 seconds; restarts your app if it's not running
- **Foreground service**: Runs as a foreground service so it's less likely to be killed by the system

## Build

**Requirements:** Java 17+ and Android SDK (or Android Studio).

### Android Studio (recommended)
1. Open the `watchdog-apk` folder in Android Studio
2. Wait for Gradle sync to finish
3. Build → Build Bundle(s) / APK(s) → Build APK(s)
4. APK output: `app/build/outputs/apk/debug/app-debug.apk`

### Command line
Ensure `JAVA_HOME` points to your JDK 17+ installation, then:

```powershell
cd watchdog-apk
.\gradlew.bat assembleDebug
```

On Linux/macOS:
```bash
cd watchdog-apk
./gradlew assembleDebug
```

## Setup

1. **Install the watchdog APK** on your signage device
2. **Open the app once** (required for boot auto-start on some devices):
   - Tap **Grant Usage Access** → enable it for Signage Watchdog
   - Tap **Start watchdog** (or it will auto-start on next boot)
   - Accept the battery optimization exemption prompt when shown
3. **Done** — the watchdog now starts automatically on boot and launches the signage player after ~27 seconds

The watchdog runs in the background (no UI after setup). It monitors `com.signage.player` and restarts it if it crashes.

**Note:** The watchdog targets API 28 so it can automatically launch the player from the background. Usage Access is required to detect when the player has stopped. Battery optimization exemption ensures the watchdog survives when the device goes to sleep.

## Permissions

- **RECEIVE_BOOT_COMPLETED**: Auto-start on boot
- **FOREGROUND_SERVICE**: Run monitoring in the background
- **POST_NOTIFICATIONS**: Required for the foreground service notification (Android 13+)
