package com.signage.watchdog;

import android.app.Application;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

/**
 * Starts WatchdogService as soon as the process starts.
 * Ensures aggressive auto-start on boot, app launch, or process restart.
 */
public class WatchdogApplication extends Application {
    private static final String TAG = "SignageWatchdog";

    @Override
    public void onCreate() {
        super.onCreate();
        Log.i(TAG, "Process started, aggressively starting WatchdogService");
        startWatchdogService();
    }

    private void startWatchdogService() {
        try {
            Intent intent = new Intent(this, WatchdogService.class);
            intent.putExtra(WatchdogService.EXTRA_SKIP_DELAY, true);  // No delay when process starts
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent);
            } else {
                startService(intent);
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed to start WatchdogService from Application", e);
        }
    }
}
