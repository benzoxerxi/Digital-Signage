package com.signage.player

import android.app.ActivityManager
import android.app.AppOpsManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.app.usage.UsageStats
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import java.util.SortedMap
import java.util.TreeMap

/**
 * Foreground service that monitors and restarts MainActivity (same app).
 * Ensures the app stays in the foreground for digital signage.
 */
class WatchdogService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var checkRunnable: Runnable? = null

    override fun onCreate() {
        super.onCreate()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, createNotification())
        val skipDelay = intent?.getBooleanExtra(EXTRA_SKIP_DELAY, false) == true
        val delay = if (skipDelay) 0 else INITIAL_LAUNCH_DELAY_MS

        handler.removeCallbacksAndMessages(null)
        handler.postDelayed({
            launchMainActivity()
            startWatchdogLoop()
        }, delay.toLong())

        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        Log.i(TAG, "Task removed, restarting service and app")
        val restart = Intent(this, WatchdogService::class.java).apply {
            putExtra(EXTRA_SKIP_DELAY, true)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(restart)
        } else {
            startService(restart)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        checkRunnable?.let { handler.removeCallbacks(it) }
    }

    private fun startWatchdogLoop() {
        checkRunnable = object : Runnable {
            override fun run() {
                if (!isAppInForeground()) {
                    Log.i(TAG, "App not in foreground, relaunching...")
                    launchMainActivity()
                }
                handler.postDelayed(this, CHECK_INTERVAL_MS.toLong())
            }
        }
        handler.postDelayed(checkRunnable!!, CHECK_INTERVAL_MS.toLong())
    }

    private fun isAppInForeground(): Boolean {
        val activityManager = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val appProcesses = activityManager.runningAppProcesses ?: return false
        for (appProcess in appProcesses) {
            if (appProcess.importance == ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND &&
                appProcess.processName == packageName) {
                return true
            }
        }
        return false
    }

    private fun launchMainActivity() {
        val launchIntent = Intent(this, MainActivity::class.java).apply {
            addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or
                Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED or
                Intent.FLAG_ACTIVITY_SINGLE_TOP or
                Intent.FLAG_ACTIVITY_NO_USER_ACTION
            )
        }

        // Use full screen intent as a backup for background start restrictions
        postFullScreenIntentNotification(launchIntent)

        try {
            startActivity(launchIntent)
            Log.i(TAG, "Launched MainActivity via startActivity")
        } catch (e: Exception) {
            Log.w(TAG, "Direct launch failed, relying on full-screen intent: ${e.message}")
        }
    }

    private fun postFullScreenIntentNotification(launchIntent: Intent) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val pending = PendingIntent.getActivity(
            this, 1, launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        createLaunchChannel()

        val notif = NotificationCompat.Builder(this, LAUNCH_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("Signage Player")
            .setContentText("Bringing player to foreground...")
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setFullScreenIntent(pending, true)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()

        val notificationManager = getSystemService(NotificationManager::class.java)
        notificationManager?.notify(LAUNCH_NOTIF_ID, notif)

        // Remove the notification after a short delay so it doesn't clutter
        handler.postDelayed({
            notificationManager?.cancel(LAUNCH_NOTIF_ID)
        }, 5000)
    }

    private fun createLaunchChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                LAUNCH_CHANNEL_ID,
                "Auto-Launch",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                setShowBadge(false)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                setSound(null, null)
                enableVibration(false)
            }
            getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
        }
    }

    private fun createNotification(): Notification {
        createNotificationChannel()
        val pending = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Signage Player active")
            .setContentText("Monitoring application state")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentIntent(pending)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(CHANNEL_ID, "Watchdog Service", NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
            }
            getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
        }
    }

    companion object {
        private const val TAG = "WatchdogService"
        private const val CHANNEL_ID = "watchdog_channel"
        private const val LAUNCH_CHANNEL_ID = "launch_channel"
        private const val NOTIFICATION_ID = 1
        private const val LAUNCH_NOTIF_ID = 2
        private const val INITIAL_LAUNCH_DELAY_MS = 2_000
        private const val CHECK_INTERVAL_MS = 5_000
        const val EXTRA_SKIP_DELAY = "skip_delay"

        fun hasUsageStatsPermission(context: Context): Boolean {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) return true
            return try {
                val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager ?: return false
                val mode = appOps.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, android.os.Process.myUid(), context.packageName)
                mode == AppOpsManager.MODE_ALLOWED
            } catch (e: Exception) {
                false
            }
        }
    }
}
