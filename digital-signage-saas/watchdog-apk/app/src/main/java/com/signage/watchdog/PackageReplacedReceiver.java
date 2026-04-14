package com.signage.watchdog;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

/**
 * Restarts the watchdog when the app is updated (reinstalled).
 * Ensures aggressive recovery after app updates.
 */
public class PackageReplacedReceiver extends BroadcastReceiver {
    private static final String TAG = "SignageWatchdog";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent != null ? intent.getAction() : null)) {
            Log.i(TAG, "App updated, aggressively restarting WatchdogService");
            try {
                Intent serviceIntent = new Intent(context, WatchdogService.class);
                serviceIntent.putExtra(WatchdogService.EXTRA_SKIP_DELAY, true);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(serviceIntent);
                } else {
                    context.startService(serviceIntent);
                }
            } catch (Exception e) {
                Log.e(TAG, "Failed to restart WatchdogService after update", e);
            }
        }
    }
}
