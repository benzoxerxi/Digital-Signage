package com.signage.player

import android.app.AlarmManager
import android.app.Application
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import kotlin.system.exitProcess

class SignagePlayerApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        
        val mainThreadHandler = Handler(Looper.getMainLooper())

        Thread.setDefaultUncaughtExceptionHandler { thread, ex ->
            Log.e("SignageApp", "FATAL EXCEPTION: ${thread.name}", ex)
            
            // Schedule a restart
            val intent = Intent(this, MainActivity::class.java)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            val pendingIntent = PendingIntent.getActivity(
                this, 0, intent, 
                PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
            )
            
            val mgr = getSystemService(Context.ALARM_SERVICE) as AlarmManager
            mgr.set(AlarmManager.RTC, System.currentTimeMillis() + 1000, pendingIntent)
            
            exitProcess(2)
        }
    }
}
