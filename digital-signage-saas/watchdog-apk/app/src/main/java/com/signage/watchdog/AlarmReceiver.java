package com.signage.watchdog;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

/**
 * Receives the alarm scheduled by BootReceiver and starts WatchdogService.
 */
public class AlarmReceiver extends BroadcastReceiver {
    private static final String TAG = "SignageWatchdog";
    static final String ACTION_START_WATCHDOG = "com.signage.watchdog.START_WATCHDOG";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (ACTION_START_WATCHDOG.equals(intent != null ? intent.getAction() : null)) {
            Log.i(TAG, "Alarm received, starting WatchdogService and launching player");
            launchPlayer(context);
            try {
                Intent serviceIntent = new Intent(context, WatchdogService.class);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(serviceIntent);
                } else {
                    context.startService(serviceIntent);
                }
            } catch (Exception e) {
                Log.e(TAG, "Failed to start WatchdogService", e);
            }
        }
    }

    private void launchPlayer(Context context) {
        try {
            Intent launch = context.getPackageManager().getLaunchIntentForPackage(WatchdogService.TARGET_PACKAGE);
            if (launch == null) {
                launch = new Intent(Intent.ACTION_MAIN);
                launch.setClassName(WatchdogService.TARGET_PACKAGE, WatchdogService.TARGET_PACKAGE + ".MainActivity");
            }
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED | Intent.FLAG_ACTIVITY_SINGLE_TOP
                | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
            context.startActivity(launch);
        } catch (Exception e) {
            Log.w(TAG, "Could not launch player at boot: " + e.getMessage());
        }
    }
}
