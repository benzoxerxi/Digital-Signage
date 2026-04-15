package com.signage.player

import android.content.Context
import android.util.Log
import java.io.File

class VideoCache(private val context: Context) {
    
    private val cacheDir: File by lazy {
        try {
            // Keep playback cache in filesDir so Android doesn't evict it like cacheDir.
            val dir = File(context.filesDir, "videos")
            if (!dir.exists()) {
                dir.mkdirs()
            }
            Log.d(TAG, "Cache directory: ${dir.absolutePath}")
            dir
        } catch (e: Exception) {
            Log.e(TAG, "Failed to create cache directory", e)
            context.filesDir // Fallback to default app files dir
        }
    }
    
    companion object {
        private const val TAG = "VideoCache"
    }
    
    fun isCached(filename: String): Boolean {
        return try {
            val file = File(cacheDir, filename)
            val exists = file.exists() && file.length() > 0
            Log.d(TAG, "Cache check for $filename: $exists")
            exists
        } catch (e: Exception) {
            Log.e(TAG, "Error checking cache for $filename", e)
            false
        }
    }
    
    fun getCachedFile(filename: String): File? {
        return try {
            val file = File(cacheDir, filename)
            if (file.exists() && file.length() > 0) file else null
        } catch (e: Exception) {
            Log.e(TAG, "Error getting cached file $filename", e)
            null
        }
    }
    
    fun saveVideo(filename: String, data: ByteArray) {
        try {
            val file = File(cacheDir, filename)
            file.writeBytes(data)
            Log.d(TAG, "Saved video: $filename (${data.size / 1024 / 1024} MB)")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save video: $filename", e)
            throw e
        }
    }
    
    fun clearCache() {
        try {
            cacheDir.listFiles()?.forEach { it.delete() }
            Log.d(TAG, "Cache cleared")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to clear cache", e)
        }
    }
    
    fun getCacheSize(): Long {
        return try {
            cacheDir.listFiles()?.sumOf { it.length() } ?: 0L
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get cache size", e)
            0L
        }
    }
}
