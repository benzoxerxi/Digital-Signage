package com.signage.player

import android.app.Application
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast

class SignagePlayerApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        
        val mainThreadHandler = Handler(Looper.getMainLooper())

        Thread.setDefaultUncaughtExceptionHandler { thread, ex ->
            Log.e("UncaughtException", "FATAL EXCEPTION: ${thread.name}", ex)
            
            mainThreadHandler.post {
                Toast.makeText(
                    applicationContext, 
                    "An unexpected error occurred. Please restart the app.", 
                    Toast.LENGTH_LONG
                ).show()
            }
        }
    }
}
