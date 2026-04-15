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

    private fun toCacheKey(logicalVideo: String): String {
        val raw = if (logicalVideo.startsWith("drive:")) {
            "drive_" + logicalVideo.removePrefix("drive:")
        } else {
            logicalVideo
        }
        return raw.replace('/', '_')
    }

    private fun logicalFromCacheKey(cacheKey: String): String {
        return if (cacheKey.startsWith("drive_")) {
            "drive:" + cacheKey.removePrefix("drive_")
        } else {
            cacheKey
        }
    }
    
    fun isCached(filename: String): Boolean {
        return try {
            val file = File(cacheDir, toCacheKey(filename))
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
            val file = File(cacheDir, toCacheKey(filename))
            if (file.exists() && file.length() > 0) file else null
        } catch (e: Exception) {
            Log.e(TAG, "Error getting cached file $filename", e)
            null
        }
    }
    
    fun saveVideo(filename: String, data: ByteArray) {
        try {
            val file = File(cacheDir, toCacheKey(filename))
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

    fun deleteByCacheKey(cacheKey: String) {
        try {
            val safeKey = cacheKey.replace('/', '_')
            val file = File(cacheDir, safeKey)
            if (file.exists()) {
                file.delete()
                Log.d(TAG, "Deleted cache file: $safeKey")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to delete cache key: $cacheKey", e)
        }
    }

    fun listManifest(): List<Map<String, Any>> {
        return try {
            val files = cacheDir.listFiles()
                ?.filter { it.isFile && it.length() > 0 }
                ?.sortedBy { it.name.lowercase() }
                ?: emptyList()
            files.map { f ->
                val key = f.name
                val logical = logicalFromCacheKey(key)
                mapOf(
                    "k" to key,
                    "l" to logical,
                    "n" to logical.substringAfterLast('/'),
                    "s" to f.length()
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to list cache manifest", e)
            emptyList()
        }
    }

    fun listLogicalVideos(): List<String> {
        return listManifest().mapNotNull { it["l"] as? String }
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
