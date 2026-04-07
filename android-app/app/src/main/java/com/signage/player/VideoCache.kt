package com.signage.player

import android.content.Context
import android.util.Log
import java.io.File

/**
 * Persistent video files under app private storage ([DIR_NAME]), not RAM.
 * (Older builds used "playback_videos"; migrated on first access.)
 * Enforces a max total size with LRU eviction (oldest lastModified removed first).
 */
class VideoCache(private val context: Context) {

    private val cacheDir: File by lazy {
        try {
            val dir = File(context.filesDir, DIR_NAME)
            if (!dir.exists()) dir.mkdirs()
            migrateLegacyPlaybackDir(dir)
            Log.d(TAG, "Device storage directory: ${dir.absolutePath}")
            dir
        } catch (e: Exception) {
            Log.e(TAG, "Failed to create media directory", e)
            File(context.filesDir, DIR_NAME).also { it.mkdirs() }
        }
    }

    private fun migrateLegacyPlaybackDir(dest: File) {
        try {
            val legacy = File(context.filesDir, LEGACY_DIR_NAME)
            if (!legacy.exists() || !legacy.isDirectory) return
            legacy.listFiles()?.forEach { f ->
                if (f.isFile && f.length() > 0) {
                    val target = File(dest, f.name)
                    if (!target.exists()) {
                        val ok = f.renameTo(target)
                        if (!ok) Log.w(TAG, "Could not move ${f.name} from legacy dir")
                    }
                }
            }
            val left = legacy.listFiles()?.isEmpty() == true
            if (left) legacy.delete()
        } catch (e: Exception) {
            Log.w(TAG, "Legacy dir migration", e)
        }
    }

    companion object {
        private const val TAG = "PlaybackStorage"
        private const val DIR_NAME = "signage_media"
        private const val LEGACY_DIR_NAME = "playback_videos"
        /** ~2 GiB cap; adjust if devices have more storage. */
        private const val MAX_CACHE_BYTES = 2L * 1024L * 1024L * 1024L
    }

    fun isCached(filename: String): Boolean {
        return try {
            val file = File(cacheDir, filename)
            file.exists() && file.length() > 0
        } catch (e: Exception) {
            Log.e(TAG, "Error checking cache for $filename", e)
            false
        }
    }

    /** Remove a single cached file by storage key (safe name under cache dir). */
    fun deleteFile(filename: String): Boolean {
        return try {
            val f = File(cacheDir, filename)
            if (!f.exists()) return true
            val ok = f.delete()
            if (ok) Log.d(TAG, "Deleted file: $filename")
            ok
        } catch (e: Exception) {
            Log.e(TAG, "deleteFile failed: $filename", e)
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

    /** Mark file as recently used (for LRU eviction). */
    fun touchFile(filename: String) {
        try {
            val file = File(cacheDir, filename)
            if (file.exists()) {
                file.setLastModified(System.currentTimeMillis())
            }
        } catch (e: Exception) {
            Log.w(TAG, "touchFile failed: $filename", e)
        }
    }

    fun saveVideo(filename: String, data: ByteArray) {
        val file = File(cacheDir, filename)
        val incoming = data.size.toLong()
        evictUntilSpaceAvailable(incoming, exclude = filename)
        try {
            file.writeBytes(data)
            touchFile(filename)
            Log.d(TAG, "Saved video: $filename (${incoming / 1024 / 1024} MB), total on device ~${getCacheSize() / 1024 / 1024} MB")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save video: $filename", e)
            throw e
        }
    }

    private fun evictUntilSpaceAvailable(incomingBytes: Long, exclude: String) {
        val files = cacheDir.listFiles()?.filter { it.isFile && it.name != exclude } ?: return
        var total = files.sumOf { it.length() }
        val targetMax = MAX_CACHE_BYTES - incomingBytes
        if (total <= targetMax) return

        val sorted = files.sortedBy { it.lastModified() }
        for (f in sorted) {
            if (total <= targetMax) break
            val len = f.length()
            if (f.delete()) {
                total -= len
                Log.d(TAG, "LRU evicted file: ${f.name} (${len / 1024 / 1024} MB)")
            }
        }
    }

    fun clearCache() {
        try {
            cacheDir.listFiles()?.forEach { it.delete() }
            File(context.filesDir, LEGACY_DIR_NAME).listFiles()?.forEach { it.delete() }
            Log.d(TAG, "Storage cleared")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to clear storage", e)
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

    /**
     * Non-empty cached files for server manifest: storage key, size bytes, lastModified ms.
     */
    fun listCachedEntries(): List<Triple<String, Long, Long>> {
        return try {
            cacheDir.listFiles()
                ?.filter { it.isFile && it.length() > 0 }
                ?.map { Triple(it.name, it.length(), it.lastModified()) }
                ?.sortedByDescending { it.third }
                ?: emptyList()
        } catch (e: Exception) {
            Log.e(TAG, "listCachedEntries failed", e)
            emptyList()
        }
    }
}
