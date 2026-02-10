package com.signage.watchdog;

import android.app.ActivityManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.AppOpsManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;
import androidx.core.app.NotificationCompat;

import java.util.List;

/**
 * Foreground service that monitors the target app and restarts it if it's not in the foreground.
 */
public class WatchdogService extends Service {
    private static final String TAG = "SignageWatchdog";
    public static final String TARGET_PACKAGE = "com.signage.player";
    public static final String EXTRA_START_PINNED = "com.signage.watchdog.START_PINNED";
    private static final String CHANNEL_ID = "watchdog_channel";
    private static final int NOTIFICATION_ID = 1;
    private static final int INITIAL_LAUNCH_DELAY_MS = 5_000;
    private static final int CHECK_INTERVAL_MS = 5_000; // Check every 5 seconds for better responsiveness
    static final String EXTRA_SKIP_DELAY = "skip_delay";

    private Handler handler;
    private Runnable checkRunnable;

    @Override
    public void onCreate() {
        super.onCreate();
        handler = new Handler(Looper.getMainLooper());
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTIFICATION_ID, createNotification());
        
        boolean skipDelay = intent != null && intent.getBooleanExtra(EXTRA_SKIP_DELAY, false);
        int delay = skipDelay ? 0 : INITIAL_LAUNCH_DELAY_MS;
        
        // Remove any existing callbacks to avoid multiple loops
        if (checkRunnable != null) {
            handler.removeCallbacks(checkRunnable);
        }

        handler.postDelayed(() -> {
            if (!isTargetInForeground()) {
                launchTargetApp();
            }
            startWatchdogLoop();
        }, delay);
        
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void startWatchdogLoop() {
        checkRunnable = new Runnable() {
            @Override
            public void run() {
                if (!isTargetInForeground()) {
                    Log.i(TAG, "Target app not in foreground, restarting: " + TARGET_PACKAGE);
                    launchTargetApp();
                }
                handler.postDelayed(this, CHECK_INTERVAL_MS);
            }
        };
        handler.postDelayed(checkRunnable, CHECK_INTERVAL_MS);
    }

    private boolean isTargetInForeground() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            return isTargetInForegroundViaUsageStats();
        }
        return isTargetInForegroundViaAM();
    }

    @SuppressWarnings("deprecation")
    private boolean isTargetInForegroundViaAM() {
        try {
            ActivityManager am = (ActivityManager) getSystemService(Context.ACTIVITY_SERVICE);
            if (am == null) return false;
            List<ActivityManager.RunningTaskInfo> tasks = am.getRunningTasks(1);
            if (tasks != null && !tasks.isEmpty()) {
                return TARGET_PACKAGE.equals(tasks.get(0).topActivity.getPackageName());
            }
        } catch (Exception e) {
            Log.e(TAG, "Error checking foreground task", e);
        }
        return false;
    }

    private boolean isTargetInForegroundViaUsageStats() {
        try {
            UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) return false;
            
            long now = System.currentTimeMillis();
            // Check events in the last 15 seconds
            UsageEvents events = usm.queryEvents(now - 15_000, now);
            UsageEvents.Event event = new UsageEvents.Event();
            String lastForegroundApp = "";
            
            while (events.hasNextEvent()) {
                events.getNextEvent(event);
                if (event.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                    lastForegroundApp = event.getPackageName();
                }
            }
            return TARGET_PACKAGE.equals(lastForegroundApp);
        } catch (Exception e) {
            Log.e(TAG, "UsageStats foreground check failed", e);
        }
        return false;
    }

    public static boolean hasUsageStatsPermission(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) return true;
        try {
            AppOpsManager appOps = (AppOpsManager) context.getSystemService(Context.APP_OPS_SERVICE);
            int mode = appOps.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                android.os.Process.myUid(), context.getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    private void launchTargetApp() {
        try {
            Intent launchIntent = getPackageManager().getLaunchIntentForPackage(TARGET_PACKAGE);
            if (launchIntent == null) {
                launchIntent = new Intent(Intent.ACTION_MAIN);
                launchIntent.setClassName(TARGET_PACKAGE, TARGET_PACKAGE + ".MainActivity");
            }
            launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED | Intent.FLAG_ACTIVITY_SINGLE_TOP
                | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
            launchIntent.putExtra(EXTRA_START_PINNED, true);
            startActivity(launchIntent);
        } catch (Exception e) {
            Log.e(TAG, "Failed to launch target app", e);
        }
    }

    private Notification createNotification() {
        createNotificationChannel();
        Intent intent = new Intent(this, ConfigActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Signage Watchdog Active")
            .setContentText("Monitoring player status...")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID,
                "Watchdog", NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        if (handler != null && checkRunnable != null) {
            handler.removeCallbacks(checkRunnable);
        }
    }
}
