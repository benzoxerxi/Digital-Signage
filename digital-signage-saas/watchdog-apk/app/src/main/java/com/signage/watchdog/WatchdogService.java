package com.signage.watchdog;

import android.app.ActivityManager;
import android.app.AlarmManager;
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
import android.os.SystemClock;
import android.util.Log;
import androidx.core.app.NotificationCompat;

import java.util.List;

/**
 * Foreground service that monitors the target app and restarts it if it's not in the foreground.
 * Designed to be persistent and survive process death.
 */
public class WatchdogService extends Service {
    private static final String TAG = "SignageWatchdog";
    public static final String TARGET_PACKAGE = "com.signage.player";
    private static final String CHANNEL_ID = "watchdog_channel";
    private static final int NOTIFICATION_ID = 1;
    private static final int INITIAL_LAUNCH_DELAY_MS = 5_000;
    private static final int CHECK_INTERVAL_MS = 30_000; // Check every 30 seconds
    private static final int HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes heartbeat
    static final String EXTRA_SKIP_DELAY = "skip_delay";

    private Handler handler;
    private Runnable checkRunnable;

    @Override
    public void onCreate() {
        super.onCreate();
        handler = new Handler(Looper.getMainLooper());
        Log.i(TAG, "WatchdogService created");
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Log.i(TAG, "WatchdogService onStartCommand");
        startForeground(NOTIFICATION_ID, createNotification());
        
        scheduleHeartbeat();

        boolean skipDelay = intent != null && intent.getBooleanExtra(EXTRA_SKIP_DELAY, false);
        int delay = skipDelay ? 0 : INITIAL_LAUNCH_DELAY_MS;
        
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
            // Check events in a window slightly larger than the check interval
            UsageEvents events = usm.queryEvents(now - (CHECK_INTERVAL_MS + 20_000), now);
            UsageEvents.Event event = new UsageEvents.Event();
            String lastForegroundApp = "";
            
            while (events.hasNextEvent()) {
                events.getNextEvent(event);
                if (event.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                    lastForegroundApp = event.getPackageName();
                } else if (event.getEventType() == UsageEvents.Event.MOVE_TO_BACKGROUND) {
                    if (TARGET_PACKAGE.equals(event.getPackageName())) {
                        lastForegroundApp = "";
                    }
                }
            }

            if (TARGET_PACKAGE.equals(lastForegroundApp)) return true;

            return isTargetInForegroundFallback(usm, now);

        } catch (Exception e) {
            Log.e(TAG, "UsageStats foreground check failed", e);
        }
        return false;
    }

    private boolean isTargetInForegroundFallback(UsageStatsManager usm, long now) {
        List<android.app.usage.UsageStats> stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, now - 3600000, now);
        if (stats == null) return false;
        long lastTimeUsed = 0;
        String topPackage = "";
        for (android.app.usage.UsageStats s : stats) {
            if (s.getLastTimeUsed() > lastTimeUsed) {
                lastTimeUsed = s.getLastTimeUsed();
                topPackage = s.getPackageName();
            }
        }
        return TARGET_PACKAGE.equals(topPackage);
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
            startActivity(launchIntent);
        } catch (Exception e) {
            Log.e(TAG, "Failed to launch target app", e);
        }
    }

    private void scheduleHeartbeat() {
        AlarmManager alarmManager = (AlarmManager) getSystemService(Context.ALARM_SERVICE);
        if (alarmManager == null) return;

        Intent intent = new Intent(this, AlarmReceiver.class);
        intent.setAction(AlarmReceiver.ACTION_START_WATCHDOG);
        PendingIntent pending = PendingIntent.getBroadcast(this, 1, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,
                    SystemClock.elapsedRealtime() + HEARTBEAT_INTERVAL_MS, pending);
        } else {
            alarmManager.set(AlarmManager.ELAPSED_REALTIME_WAKEUP,
                    SystemClock.elapsedRealtime() + HEARTBEAT_INTERVAL_MS, pending);
        }
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        Log.i(TAG, "Task removed, restarting service");
        Intent restartIntent = new Intent(getApplicationContext(), WatchdogService.class);
        restartIntent.putExtra(EXTRA_SKIP_DELAY, true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(restartIntent);
        } else {
            startService(restartIntent);
        }
    }

    private Notification createNotification() {
        createNotificationChannel();
        Intent intent = new Intent(this, ConfigActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Signage Watchdog Running")
            .setContentText("Monitoring player every 30s. Do not close.")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID,
                "Watchdog Service", NotificationManager.IMPORTANCE_MIN);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        Log.i(TAG, "WatchdogService onDestroy");
        if (handler != null && checkRunnable != null) {
            handler.removeCallbacks(checkRunnable);
        }
        // If destroyed, try to restart
        Intent restartIntent = new Intent(this, WatchdogService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(restartIntent);
        } else {
            startService(restartIntent);
        }
    }
}
