package com.signage.watchdog;

import android.app.AlarmManager;
import android.content.BroadcastReceiver;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.SystemClock;
import android.util.Log;

/**
 * Receives boot events and starts the WatchdogService.
 * Handles both locked (pre-UI) and unlocked boot states.
 */
public class BootReceiver extends BroadcastReceiver {
    private static final String TAG = "SignageWatchdog";
    private static final int BOOT_DELAY_MS = 10_000;

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent != null ? intent.getAction() : null;
        Log.i(TAG, "BootReceiver trigger: " + action);

        if (Intent.ACTION_BOOT_COMPLETED.equals(action) ||
            Intent.ACTION_LOCKED_BOOT_COMPLETED.equals(action) ||
            Intent.ACTION_USER_PRESENT.equals(action) ||
            "android.intent.action.QUICKBOOT_POWERON".equals(action)) {

            // 1. Try to start immediately
            startService(context);

            // 2. Schedule a backup start via AlarmManager in case the system kills the initial start
            scheduleBackupStart(context);
        }
    }

    private void startService(Context context) {
        try {
            Intent serviceIntent = new Intent(context, WatchdogService.class);
            serviceIntent.putExtra(WatchdogService.EXTRA_SKIP_DELAY, false);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent);
            } else {
                context.startService(serviceIntent);
            }
            Log.i(TAG, "WatchdogService start requested from BootReceiver");
        } catch (Exception e) {
            Log.e(TAG, "Failed to start service immediately on boot", e);
        }
    }

    private void scheduleBackupStart(Context context) {
        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (alarmManager == null) return;

        Intent alarmIntent = new Intent(context, AlarmReceiver.class);
        alarmIntent.setAction(AlarmReceiver.ACTION_START_WATCHDOG);

        PendingIntent pending = PendingIntent.getBroadcast(context, 0, alarmIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        long triggerAt = SystemClock.elapsedRealtime() + BOOT_DELAY_MS;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pending);
        } else {
            alarmManager.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pending);
        }
    }
}
