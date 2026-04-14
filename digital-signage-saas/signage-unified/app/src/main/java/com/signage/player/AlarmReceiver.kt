package com.signage.player

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == ACTION_START_WATCHDOG) {
            launchMainActivityOnTop(context)
            val serviceIntent = Intent(context, WatchdogService::class.java).apply {
                putExtra(WatchdogService.EXTRA_SKIP_DELAY, true)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
        }
    }

    private fun launchMainActivityOnTop(context: Context) {
        val launch = Intent(context, MainActivity::class.java).apply {
            addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or
                Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED or
                Intent.FLAG_ACTIVITY_SINGLE_TOP
            )
        }
        try {
            context.startActivity(launch)
        } catch (_: Exception) { }
    }

    companion object {
        const val ACTION_START_WATCHDOG = "com.signage.unified.START_WATCHDOG"
    }
}
