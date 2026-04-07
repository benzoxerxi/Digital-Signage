package com.signage.player

import android.app.ActivityManager
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.Base64
import android.util.Log
import android.view.PixelCopy
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.RelativeLayout
import android.widget.TextView
import android.widget.Toast
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import coil.ImageLoader
import coil.decode.SvgDecoder
import coil.request.ImageRequest
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine

class MainActivity : AppCompatActivity() {

    private lateinit var playerView: PlayerView
    private lateinit var screensaverView: ImageView
    private lateinit var layoutRoot: FrameLayout
    private var player: ExoPlayer? = null
    private val layoutVideoPlayers = mutableListOf<ExoPlayer>()
    private val apiClient = ApiClient()
    private lateinit var videoCache: VideoCache

    private var currentPlaylist: List<Video> = emptyList()
    private var currentVideoIndex = 0
    private var playlistSettings = PlaylistSettings()

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private val handler = Handler(Looper.getMainLooper())

    private var serverUrl = ""
    private var connectionCode = ""
    private var deviceId = ""
    private var deviceName = ""
    private var lastCommandId = -1
    private var currentProgramId: String? = null
    private var inLayoutMode = false
    private val heartbeatBusy = AtomicBoolean(false)
    private var lastPlaylistRefreshAt = 0L
    /** When true, do not resume from playlist (set by format/clear_cache; cleared when server sends explicit play). */
    private var doNotResumeFromPlaylist = false

    companion object {
        private const val TAG = "SignagePlayer"
        private const val PREFS_NAME = "SignagePrefs"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_CONNECTION_CODE = "connection_code"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_DEVICE_NAME = "device_name"
        private const val KEY_CACHED_VIDEO_FILENAME = "cached_video_filename"
        private const val KEY_CACHED_VIDEO_DISPLAY_NAME = "cached_video_display_name"
        /** JSON object: cache storage key -> human-readable label (playlist/command name). */
        private const val KEY_CACHE_FILE_LABELS = "cache_file_labels_json"
        private const val UPDATE_INTERVAL = 3000L
        /** Avoid hammering /api/playlist every heartbeat; reduces network contention with video streaming. */
        private const val PLAYLIST_REFRESH_MS = 30_000L
        private const val SCREENSAVER_URL = "https://karchershop.ge/cdn/shop/files/logo_karcher_2015.svg?v=1683099671&width=600"
        private const val LOGO_URL = "https://images.seeklogo.com/logo-png/43/2/karcher-logo-png_seeklogo-437949.png"
        /** Default server URL – no server input needed; user only enters 9-digit code */
        private const val DEFAULT_SERVER_URL = "https://benzos.uk/signage"
        /** Intent extra from watchdog: start pinned (lock task) when launched by watchdog */
        private const val EXTRA_START_PINNED = "com.signage.watchdog.START_PINNED"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        try {
            videoCache = VideoCache(this)
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            setContentView(R.layout.activity_main)
            hideSystemUI()

            layoutRoot = findViewById(R.id.layout_root)
            playerView = findViewById(R.id.player_view)
            screensaverView = findViewById(R.id.screensaver_view)

            loadScreensaver()
        } catch (e: Exception) {
            Log.e(TAG, "Error in onCreate", e)
            Toast.makeText(this, "App initialization failed: ${e.message}", Toast.LENGTH_LONG).show()
            return
        }

        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        // Always use the fixed backend URL. We deliberately ignore any stored server_url
        // so the only thing users ever configure is the 9-digit connection code.
        serverUrl = DEFAULT_SERVER_URL
        connectionCode = prefs.getString(KEY_CONNECTION_CODE, "") ?: ""
        deviceId = prefs.getString(KEY_DEVICE_ID, "") ?: ""
        deviceName = prefs.getString(KEY_DEVICE_NAME, "") ?: ""

        if (deviceId.isEmpty()) {
            deviceId = generateDeviceId()
            prefs.edit().putString(KEY_DEVICE_ID, deviceId).apply()
        }

        if (deviceName.isEmpty()) {
            deviceName = "Android-${Build.MODEL}"
            prefs.edit().putString(KEY_DEVICE_NAME, deviceName).apply()
        }

        Log.d(TAG, "Device ID: $deviceId")
        Log.d(TAG, "Server: $serverUrl")
        Log.d(TAG, "Connection code: ${if (connectionCode.isEmpty()) "not set" else "set"}")

        if (connectionCode.isEmpty()) {
            showSetupScreen()
        } else {
            initializePlayer()
            tryPlayCachedVideoLoop()
            startDeviceHeartbeat()
        }
        tryStartLockTaskIfRequested(intent)
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        tryStartLockTaskIfRequested(intent)
    }

    private fun tryStartLockTaskIfRequested(intent: android.content.Intent?) {
        if (intent?.getBooleanExtra(EXTRA_START_PINNED, false) != true) return
        try {
            val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                if (am.lockTaskModeState == ActivityManager.LOCK_TASK_MODE_NONE) startLockTask()
            } else {
                @Suppress("DEPRECATION")
                if (!am.isInLockTaskMode) startLockTask()
            }
        } catch (_: Exception) {}
    }

    private fun generateDeviceId(): String {
        var androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        if (androidId == null || androidId == "9774d56d682e549c") {
            androidId = "android_${System.currentTimeMillis()}"
        }
        return "android_$androidId"
    }

    /** Called when server reports device was removed from panel. Clear connection and show setup so user can reconnect. */
    private fun goBackToSetup() {
        connectionCode = ""
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_CONNECTION_CODE, connectionCode)
            .apply()
        apiClient.setConnectionCode("")
        showSetupScreen()
    }

    private fun showSetupScreen() {
        setContentView(R.layout.activity_setup)
        val serverSection = findViewById<View>(R.id.server_section)
        val serverInput = findViewById<android.widget.EditText>(R.id.server_input)
        val codeInput = findViewById<android.widget.EditText>(R.id.connection_code_input)
        val screenNameInput = findViewById<android.widget.EditText>(R.id.screen_name_input)
        val connectButton = findViewById<android.widget.Button>(R.id.connect_button)
        val logoView = findViewById<ImageView>(R.id.logo_view)

        if (serverUrl.isEmpty()) serverUrl = DEFAULT_SERVER_URL
        serverSection.visibility = View.VISIBLE
        serverInput.setText(serverUrl)
        if (connectionCode.isNotEmpty()) codeInput.setText(connectionCode)
        if (deviceName.isNotEmpty()) screenNameInput.setText(deviceName)

        val imageLoader = ImageLoader.Builder(this).build()
        val request = ImageRequest.Builder(this)
            .data(LOGO_URL)
            .target(logoView)
            .build()
        imageLoader.enqueue(request)

        connectButton.setOnClickListener {
            val code = codeInput.text.toString().trim().replace(Regex("[^0-9]"), "")
            when {
                code.length != 9 -> Toast.makeText(this, "Please enter your 9-digit connection code", Toast.LENGTH_SHORT).show()
                else -> {
                    val inputUrl = serverInput.text.toString().trim()
                    serverUrl = if (inputUrl.isNotEmpty()) inputUrl else DEFAULT_SERVER_URL

                    connectionCode = code
                    val name = screenNameInput.text.toString().trim()
                    deviceName = if (name.isNotEmpty()) name else "Android-${Build.MODEL}"
                    getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                        .edit()
                        .putString(KEY_SERVER_URL, serverUrl)
                        .putString(KEY_CONNECTION_CODE, connectionCode)
                        .putString(KEY_DEVICE_NAME, deviceName)
                        .apply()
                    apiClient.setBaseUrl(serverUrl)
                    apiClient.setConnectionCode(connectionCode)
                    testConnection()
                }
            }
        }
    }

    private fun testConnection() {
        scope.launch {
            try {
                val status = withContext(Dispatchers.IO) {
                    apiClient.getStatus()
                }
                if (!status.online) {
                    Toast.makeText(this@MainActivity, "Server not responding", Toast.LENGTH_SHORT).show()
                    return@launch
                }
                // Validate 9-digit code with playback state (from_setup=1 so server allows re-add if device was removed)
                withContext(Dispatchers.IO) {
                    apiClient.getPlaybackState(connectionCode, deviceId, deviceName, fromSetup = true)
                }

                Toast.makeText(this@MainActivity, "Connected successfully!", Toast.LENGTH_SHORT).show()

                setContentView(R.layout.activity_main)
                layoutRoot = findViewById(R.id.layout_root)
                playerView = findViewById(R.id.player_view)
                screensaverView = findViewById(R.id.screensaver_view)
                inLayoutMode = false
                currentProgramId = null
                layoutVideoPlayers.clear()
                hideSystemUI()
                loadScreensaver()
                showScreensaver(true)

                initializePlayer()
                tryPlayCachedVideoLoop()
                startDeviceHeartbeat()
            } catch (e: Exception) {
                Log.e(TAG, "Connection failed", e)
                val msg = when {
                    e.message?.contains("404") == true -> "Invalid 9-digit code. Check Account settings."
                    e.message?.contains("403") == true -> "Account inactive or subscription expired."
                    else -> "Connection failed: ${e.message}"
                }
                Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
            }
        }
    }

    /** Larger buffers reduce rebuffering stutter on uneven Wi‑Fi / shared bandwidth with polling. */
    private fun buildBufferedExoPlayer(): ExoPlayer {
        val loadControl = DefaultLoadControl.Builder()
            .setBufferDurationsMs(
                30_000,
                120_000,
                2_500,
                5_000
            )
            .build()
        return ExoPlayer.Builder(this).setLoadControl(loadControl).build()
    }

    private fun initializePlayer() {
        try {
            player = buildBufferedExoPlayer().also { exoPlayer ->
                playerView.player = exoPlayer
                playerView.useController = false

                exoPlayer.addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(playbackState: Int) {
                        if (playbackState == Player.STATE_IDLE) {
                            showScreensaver(true)
                        } else {
                            showScreensaver(false)
                        }

                        when (playbackState) {
                            Player.STATE_ENDED -> {
                                handler.post { playNextVideo() }
                            }
                            Player.STATE_READY -> {
                                Log.d(TAG, "Video ready to play")
                            }
                        }
                    }

                    override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                        Log.e(TAG, "Playback error", error)
                        Toast.makeText(this@MainActivity, "Playback error. Skipping.", Toast.LENGTH_SHORT).show()
                        handler.post { playNextVideo() }
                    }
                })
            }

            apiClient.setBaseUrl(serverUrl)
            apiClient.setConnectionCode(connectionCode)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to initialize player", e)
            Toast.makeText(this, "Player initialization failed", Toast.LENGTH_SHORT).show()
        }
    }

    private fun startDeviceHeartbeat() {
        handler.post(object : Runnable {
            override fun run() {
                sendHeartbeatAndCheckCommands()
                handler.postDelayed(this, UPDATE_INTERVAL)
            }
        })
    }

    /**
     * Heartbeat: fetch playback state (updates server last_seen) and layout in parallel when possible,
     * skip overlapping ticks, and throttle playlist polling so HTTP does not compete with video.
     */
    private fun sendHeartbeatAndCheckCommands() {
        if (connectionCode.isEmpty()) return
        if (!heartbeatBusy.compareAndSet(false, true)) return
        scope.launch {
            try {
                val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                val cachedVideo = prefs.getString(KEY_CACHED_VIDEO_FILENAME, null) ?: ""
                val cachedVideoName = prefs.getString(KEY_CACHED_VIDEO_DISPLAY_NAME, null) ?: ""

                val (playbackState, layoutResponse) = coroutineScope {
                    val manifestJson = buildCacheManifestForHeartbeat()
                    val playbackDeferred = async(Dispatchers.IO) {
                        apiClient.getPlaybackState(
                            connectionCode,
                            deviceId,
                            deviceName,
                            fromSetup = false,
                            currentVideoFromCache = cachedVideo,
                            currentVideoNameFromCache = cachedVideoName,
                            cacheManifestJson = manifestJson
                        )
                    }
                    val layoutDeferred = async(Dispatchers.IO) {
                        apiClient.getDeviceLayout(deviceId)
                    }
                    Pair(playbackDeferred.await(), layoutDeferred.await())
                }

                if (playbackState.removed == true) {
                    Log.d(TAG, "Device was removed from panel - returning to setup")
                    runOnUiThread { goBackToSetup() }
                    return@launch
                }

                Log.d(TAG, "Heartbeat. Command ID: ${playbackState.command_id}, video: ${playbackState.current_video}")

                if (!playbackState.device_name.isNullOrEmpty() && playbackState.device_name != deviceName) {
                    Log.d(TAG, "Server updated device name: $deviceName → ${playbackState.device_name}")
                    deviceName = playbackState.device_name
                    prefs.edit().putString(KEY_DEVICE_NAME, deviceName).apply()
                }

                if (playbackState.screenshot_requested == true) {
                    Log.d(TAG, "Screenshot requested by server")
                    captureAndUploadScreenshot()
                }

                if (playbackState.clear_cache == true) {
                    Log.d(TAG, "clear_cache requested – stopping and clearing")
                    doNotResumeFromPlaylist = true
                    exitLayoutMode()
                    player?.stop()
                    showScreensaver(true)
                    clearVideoCache()
                    currentPlaylist = emptyList()
                    currentVideoIndex = 0
                    lastCommandId = playbackState.command_id
                    return@launch
                }

                val activeProgram = layoutResponse?.program?.takeIf { it.elements.isNotEmpty() }
                if (activeProgram != null) {
                    if (activeProgram.id != currentProgramId) {
                        exitLayoutMode()
                        currentProgramId = activeProgram.id
                        inLayoutMode = true
                        Log.d(TAG, "Entering layout mode: ${activeProgram.name} (${activeProgram.id})")
                        renderProgramLayout(activeProgram)
                    }
                    return@launch
                }

                if (inLayoutMode) {
                    Log.d(TAG, "Exiting layout mode, returning to legacy playback")
                    exitLayoutMode()
                }

                if (playbackState.command_id != lastCommandId) {
                    Log.d(TAG, "New command: $lastCommandId → ${playbackState.command_id}")
                    lastCommandId = playbackState.command_id
                    lastPlaylistRefreshAt = 0L

                    if (playbackState.current_video != null) {
                        Log.d(TAG, "Server commanded to play: ${playbackState.current_video} cacheOnly=${playbackState.playback_cache_only}")
                        doNotResumeFromPlaylist = false
                        playSpecificVideo(
                            playbackState.current_video,
                            playbackState.video_url,
                            cacheOnly = playbackState.playback_cache_only,
                            labelForCache = playbackState.current_video_name
                        )
                        if (!playbackState.current_video_name.isNullOrEmpty()) {
                            prefs.edit()
                                .putString(KEY_CACHED_VIDEO_DISPLAY_NAME, playbackState.current_video_name).apply()
                        }
                    } else if (playbackState.command_id > 0) {
                        Log.d(TAG, "Stop/format command – stopping playback")
                        doNotResumeFromPlaylist = true
                        player?.stop()
                        showScreensaver(true)
                        clearVideoCache()
                        currentPlaylist = emptyList()
                        currentVideoIndex = 0
                    } else {
                        Log.d(TAG, "Server state reset; keeping cached playback")
                    }
                } else {
                    if (!doNotResumeFromPlaylist &&
                        (currentPlaylist.isNotEmpty() || playbackState.current_video != null)
                    ) {
                        val now = SystemClock.elapsedRealtime()
                        if (now - lastPlaylistRefreshAt >= PLAYLIST_REFRESH_MS) {
                            lastPlaylistRefreshAt = now
                            updatePlaylist()
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Heartbeat failed (server may be restarting); keeping playback", e)
            } finally {
                heartbeatBusy.set(false)
            }
        }
    }

    private fun exitLayoutMode() {
        if (inLayoutMode) {
            layoutRoot.removeAllViews()
            layoutVideoPlayers.forEach { it.release() }
            layoutVideoPlayers.clear()
            playerView.visibility = View.VISIBLE
            inLayoutMode = false
            currentProgramId = null
        }
    }

    private fun clearVideoCache() {
        scope.launch(Dispatchers.IO) {
            try {
                val cacheSize = videoCache.getCacheSize()
                videoCache.clearCache()
                withContext(Dispatchers.Main) {
                    getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                        .edit()
                        .remove(KEY_CACHED_VIDEO_FILENAME)
                        .remove(KEY_CACHED_VIDEO_DISPLAY_NAME)
                        .remove(KEY_CACHE_FILE_LABELS)
                        .apply()
                }
                val sizeMB = cacheSize / (1024 * 1024)
                Log.d(TAG, "Video cache cleared: ${sizeMB}MB freed")
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        this@MainActivity,
                        "Cache cleared: ${sizeMB}MB freed",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to clear cache", e)
            }
        }
    }

    /** Cache key for storage: sanitize drive:ID to drive_ID so filenames are filesystem-safe. */
    private fun cacheKey(filename: String): String = filename.replace(":", "_")

    /** Reverse of [cacheKey] for Drive files; other keys stay as-is. */
    private fun logicalFilenameFromCacheKey(key: String): String {
        if (key.startsWith("drive_")) return "drive:" + key.removePrefix("drive_")
        return key
    }

    private fun rememberCacheLabel(cacheKey: String, label: String?) {
        val t = label?.trim().orEmpty()
        if (t.isEmpty()) return
        try {
            val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val raw = prefs.getString(KEY_CACHE_FILE_LABELS, null) ?: "{}"
            val o = try {
                JSONObject(raw)
            } catch (_: Exception) {
                JSONObject()
            }
            o.put(cacheKey, t)
            prefs.edit().putString(KEY_CACHE_FILE_LABELS, o.toString()).apply()
        } catch (_: Exception) { }
    }

    /** Compact list of cached files for server (dashboard “play from cache”). */
    private fun buildCacheManifestForHeartbeat(): String {
        return try {
            val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val labelsJson = try {
                JSONObject(prefs.getString(KEY_CACHE_FILE_LABELS, null) ?: "{}")
            } catch (_: Exception) {
                JSONObject()
            }
            val arr = JSONArray()
            val entries = videoCache.listCachedEntries()
            val maxItems = if (entries.size > 40) 25 else 50
            for ((key, size, _) in entries.take(maxItems)) {
                val o = JSONObject()
                o.put("k", key)
                o.put("s", size)
                o.put("l", logicalFilenameFromCacheKey(key))
                if (labelsJson.has(key)) {
                    o.put("n", labelsJson.optString(key, ""))
                }
                arr.put(o)
            }
            var s = arr.toString()
            if (s.length > 6000) {
                val small = JSONArray()
                for (i in 0 until minOf(arr.length(), 15)) {
                    small.put(arr.get(i))
                }
                s = small.toString()
            }
            s
        } catch (e: Exception) {
            Log.w(TAG, "buildCacheManifest failed", e)
            "[]"
        }
    }

    private fun playSpecificVideo(
        filename: String,
        videoUrl: String? = null,
        cacheOnly: Boolean = false,
        labelForCache: String? = null,
    ) {
        val key = cacheKey(filename)
        scope.launch {
            try {
                if (!videoCache.isCached(key)) {
                    if (cacheOnly) {
                        Log.w(TAG, "cache_only command but file missing: $key")
                        withContext(Dispatchers.Main) {
                            Toast.makeText(
                                this@MainActivity,
                                "Not on device yet — play once online or wait for download.",
                                Toast.LENGTH_LONG
                            ).show()
                        }
                        return@launch
                    }
                    Log.d(TAG, "Video not cached, downloading: $filename")
                    val videoData = withContext(Dispatchers.IO) {
                        if (!videoUrl.isNullOrEmpty()) {
                            apiClient.downloadFromUrl(videoUrl)
                        } else {
                            apiClient.downloadVideo(filename)
                        }
                    }
                    videoCache.saveVideo(key, videoData)
                    rememberCacheLabel(key, labelForCache ?: filename)
                } else {
                    videoCache.touchFile(key)
                    if (!labelForCache.isNullOrBlank()) rememberCacheLabel(key, labelForCache)
                }

                val cachedFile = videoCache.getCachedFile(key)
                if (cachedFile != null && cachedFile.exists()) {
                    showScreensaver(false)
                    val mediaItem = MediaItem.fromUri(Uri.fromFile(cachedFile))
                    player?.apply {
                        setMediaItem(mediaItem)
                        repeatMode = Player.REPEAT_MODE_OFF
                        prepare()
                        play()
                    }
                    getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                        .edit()
                        .putString(KEY_CACHED_VIDEO_FILENAME, key)
                        .apply()
                    Log.d(TAG, "Playing commanded video: $filename")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to play commanded video: $filename", e)
            }
        }
    }

    /** On startup or after reconnect: if we have a cached video filename and file exists, play it in a loop (offline resilience). */
    private fun tryPlayCachedVideoLoop() {
        val filename = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_CACHED_VIDEO_FILENAME, null) ?: return
        val cachedFile = videoCache.getCachedFile(filename) ?: return
        if (!cachedFile.exists()) return
        scope.launch {
            showScreensaver(false)
            val mediaItem = MediaItem.fromUri(Uri.fromFile(cachedFile))
            player?.apply {
                setMediaItem(mediaItem)
                repeatMode = Player.REPEAT_MODE_ONE
                prepare()
                play()
            }
            Log.d(TAG, "Playing cached video on startup (loop): $filename")
        }
    }

    private fun updatePlaylist() {
        scope.launch {
            try {
                val playlist = withContext(Dispatchers.IO) {
                    apiClient.getPlaylist()
                }

                playlistSettings = playlist.settings

                // If server told us to stop/format, do not repopulate playlist or start playback
                // (e.g. in-flight updatePlaylist finishing after format).
                if (doNotResumeFromPlaylist) return@launch

                if (playlist.videos.isEmpty()) {
                    if (currentPlaylist.isNotEmpty()) {
                        showScreensaver(true)
                        player?.stop()
                        currentPlaylist = emptyList()
                    }
                    return@launch
                }

                if (playlist.videos != currentPlaylist) {
                    Log.d(TAG, "Playlist updated: ${playlist.videos.size} videos")
                    currentPlaylist = playlist.videos
                    downloadVideos(playlist.videos, currentVideoIndex)

                    if (doNotResumeFromPlaylist) return@launch

                    // If nothing is currently playing, start the playlist from
                    // the beginning. This ensures that when a playlist is activated
                    // the device cycles through all videos in the playlist.
                    if (player?.isPlaying != true && currentPlaylist.isNotEmpty()) {
                        currentVideoIndex = 0
                        playCurrentVideo()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to update playlist", e)
            }
        }
    }

    private fun downloadVideos(videos: List<Video>, playlistCurrentIndex: Int? = null) {
        if (videos.isEmpty()) return
        scope.launch(Dispatchers.IO) {
            val n = videos.size
            val ordered = videos.mapIndexed { idx, v -> idx to v }.sortedBy { (idx, video) ->
                val key = cacheKey(video.filename)
                when {
                    videoCache.isCached(key) -> 200 + idx
                    playlistCurrentIndex != null && idx == playlistCurrentIndex -> 0
                    playlistCurrentIndex != null && n > 0 && idx == (playlistCurrentIndex + 1) % n -> 1
                    else -> 10 + idx
                }
            }
            for ((_, video) in ordered) {
                if (doNotResumeFromPlaylist) return@launch
                try {
                    val key = cacheKey(video.filename)
                    if (!videoCache.isCached(key)) {
                        Log.d(TAG, "Downloading: ${video.filename}")
                        val videoData = if (!video.url.isNullOrEmpty()) {
                            apiClient.downloadFromUrl(video.url)
                        } else {
                            apiClient.downloadVideo(video.filename)
                        }
                        videoCache.saveVideo(key, videoData)
                        rememberCacheLabel(key, video.name)
                        Log.d(TAG, "Downloaded: ${video.filename}")
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to download ${video.filename}", e)
                }
            }
        }
    }

    private fun prefetchNextPlaylistVideo() {
        if (currentPlaylist.size < 2) return
        val nextIdx = (currentVideoIndex + 1) % currentPlaylist.size
        val video = currentPlaylist[nextIdx]
        scope.launch(Dispatchers.IO) {
            try {
                if (doNotResumeFromPlaylist) return@launch
                val key = cacheKey(video.filename)
                if (videoCache.isCached(key)) return@launch
                Log.d(TAG, "Prefetch next playlist item: ${video.filename}")
                val videoData = if (!video.url.isNullOrEmpty()) {
                    apiClient.downloadFromUrl(video.url)
                } else {
                    apiClient.downloadVideo(video.filename)
                }
                videoCache.saveVideo(key, videoData)
                rememberCacheLabel(key, video.name)
            } catch (e: Exception) {
                Log.w(TAG, "Prefetch failed: ${video.filename}", e)
            }
        }
    }

    private fun playCurrentVideo() {
        if (currentPlaylist.isEmpty()) {
            showScreensaver(true)
            Log.w(TAG, "No videos in playlist")
            return
        }

        showScreensaver(false)
        val video = currentPlaylist[currentVideoIndex]
        val key = cacheKey(video.filename)
        val cachedFile = videoCache.getCachedFile(key)

        if (cachedFile != null && cachedFile.exists()) {
            videoCache.touchFile(key)
            val mediaItem = MediaItem.fromUri(Uri.fromFile(cachedFile))
            player?.apply {
                setMediaItem(mediaItem)
                repeatMode = Player.REPEAT_MODE_OFF
                prepare()
                play()
            }
            getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_CACHED_VIDEO_FILENAME, key)
                .putString(KEY_CACHED_VIDEO_DISPLAY_NAME, video.name)
                .apply()
            rememberCacheLabel(key, video.name)
            Log.d(TAG, "Playing: ${video.name} (${currentVideoIndex + 1}/${currentPlaylist.size})")
            prefetchNextPlaylistVideo()
        } else {
            Log.w(TAG, "Video not cached: ${video.filename}")
            handler.postDelayed({ playNextVideo() }, 1000)
        }
    }

    private fun playNextVideo() {
        if (currentPlaylist.isEmpty()) {
            showScreensaver(true)
            return
        }

        currentVideoIndex++

        if (currentVideoIndex >= currentPlaylist.size) {
            if (playlistSettings.loop) {
                currentVideoIndex = 0
                playCurrentVideo()
            } else {
                showScreensaver(true)
                Log.d(TAG, "Playlist ended")
            }
        } else {
            playCurrentVideo()
        }
    }

    private fun hideSystemUI() {
        try {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
                window.setDecorFitsSystemWindows(false)
                window.insetsController?.let {
                    it.hide(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.navigationBars())
                    it.systemBarsBehavior = android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                }
            } else {
                @Suppress("DEPRECATION")
                window.decorView.systemUiVisibility = (
                        View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                                or View.SYSTEM_UI_FLAG_FULLSCREEN
                        )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to hide system UI", e)
        }
    }

    private fun loadScreensaver() {
        // Always use a solid white background for the screensaver
        try {
            window.decorView.setBackgroundColor(android.graphics.Color.WHITE)
        } catch (_: IllegalArgumentException) {
            // Ignore; default window background will remain
        }

        // Logo size: 70% of screen width (height follows via adjustViewBounds)
        val screenWidthPx = resources.displayMetrics.widthPixels
        val logoWidthPx = (screenWidthPx * 0.7f).toInt()
        val params = (screensaverView.layoutParams as? RelativeLayout.LayoutParams)
            ?: RelativeLayout.LayoutParams(logoWidthPx, android.view.ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                addRule(RelativeLayout.CENTER_IN_PARENT)
            }
        params.width = logoWidthPx
        params.height = android.view.ViewGroup.LayoutParams.WRAP_CONTENT
        screensaverView.layoutParams = params
        screensaverView.adjustViewBounds = true

        val imageLoader = ImageLoader.Builder(this)
            .components {
                add(SvgDecoder.Factory())
            }
            .build()

        val request = ImageRequest.Builder(this)
            .data(SCREENSAVER_URL)
            .target(screensaverView)
            .build()

        imageLoader.enqueue(request)
    }

    private fun showScreensaver(show: Boolean) {
        if (show) {
            // If we have a cached video, prefer playing it instead of showing the static screensaver.
            // This gives offline resilience: keep casting cached content whenever possible.
            val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val filename = prefs.getString(KEY_CACHED_VIDEO_FILENAME, null)
            val cachedFile = if (filename != null) videoCache.getCachedFile(filename) else null

            if (cachedFile != null && cachedFile.exists()) {
                // This will call showScreensaver(false) internally and start playback.
                tryPlayCachedVideoLoop()
                return
            }
        }

        // Fallback: show or hide the static screensaver image.
        screensaverView.visibility = if (show) View.VISIBLE else View.GONE
        playerView.visibility = if (show) View.GONE else View.VISIBLE
    }

    /**
     * Capture screenshot of current screen and upload to server
     */
    private fun captureAndUploadScreenshot() {
        scope.launch {
            try {
                Log.d(TAG, "Starting screenshot capture...")
                Log.d(TAG, "Player state: isPlaying=${player?.isPlaying}, currentPosition=${player?.currentPosition}")
                
                val bitmap = withContext(Dispatchers.Main) {
                    // Try multiple methods in order of preference
                    var capturedBitmap: Bitmap? = null
                    
                    // Method 1: PixelCopy (Android 8.0+) - Best for video
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        Log.d(TAG, "Trying PixelCopy method...")
                        capturedBitmap = captureScreenWithPixelCopy()
                        if (capturedBitmap != null) {
                            Log.d(TAG, "PixelCopy successful")
                        } else {
                            Log.w(TAG, "PixelCopy failed, trying alternative...")
                        }
                    }
                    
                    // Method 2: Direct PlayerView bitmap capture
                    if (capturedBitmap == null && player?.isPlaying == true) {
                        Log.d(TAG, "Trying PlayerView capture...")
                        capturedBitmap = capturePlayerView()
                        if (capturedBitmap != null) {
                            Log.d(TAG, "PlayerView capture successful")
                        }
                    }
                    
                    // Method 3: Root view capture (fallback)
                    if (capturedBitmap == null) {
                        Log.d(TAG, "Trying root view capture...")
                        capturedBitmap = captureScreenWithDrawingCache()
                    }
                    
                    capturedBitmap
                }
                
                if (bitmap == null) {
                    Log.e(TAG, "All screenshot methods failed - bitmap is null")
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            this@MainActivity,
                            "Screenshot failed - no capture method worked",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                    return@launch
                }
                
                Log.d(TAG, "Screenshot captured: ${bitmap.width}x${bitmap.height}")
                
                // Check if bitmap is all black (failed capture)
                val isBlack = withContext(Dispatchers.Default) {
                    checkIfBitmapIsBlack(bitmap)
                }
                
                if (isBlack) {
                    Log.w(TAG, "Warning: Screenshot appears to be all black")
                }
                
                // Convert to base64
                val base64Screenshot = withContext(Dispatchers.Default) {
                    val outputStream = ByteArrayOutputStream()
                    bitmap.compress(Bitmap.CompressFormat.JPEG, 85, outputStream)
                    val byteArray = outputStream.toByteArray()
                    bitmap.recycle()
                    
                    val base64 = Base64.encodeToString(byteArray, Base64.NO_WRAP)
                    "data:image/jpeg;base64,$base64"
                }
                
                val sizeKB = base64Screenshot.length / 1024
                Log.d(TAG, "Screenshot converted to base64: ${sizeKB}KB")
                
                // Upload to server
                withContext(Dispatchers.IO) {
                    apiClient.uploadScreenshot(connectionCode, deviceId, base64Screenshot)
                }
                
                Log.d(TAG, "✅ Screenshot uploaded successfully!")
                
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        this@MainActivity,
                        "Screenshot uploaded (${sizeKB}KB)",
                        Toast.LENGTH_SHORT
                    ).show()
                }
                
            } catch (e: Exception) {
                Log.e(TAG, "❌ Screenshot capture/upload failed", e)
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        this@MainActivity,
                        "Screenshot error: ${e.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }
    }
    
    /**
     * Check if bitmap is completely black (failed capture indicator)
     */
    private fun checkIfBitmapIsBlack(bitmap: Bitmap): Boolean {
        val sampleSize = 100
        var blackPixels = 0
        val totalSamples = sampleSize
        
        for (i in 0 until sampleSize) {
            val x = (bitmap.width * i) / sampleSize
            val y = bitmap.height / 2
            val pixel = bitmap.getPixel(x, y)
            val red = (pixel shr 16) and 0xff
            val green = (pixel shr 8) and 0xff
            val blue = pixel and 0xff
            
            if (red < 10 && green < 10 && blue < 10) {
                blackPixels++
            }
        }
        
        return blackPixels > (totalSamples * 0.9)
    }
    
    /**
     * Try to capture directly from PlayerView
     */
    private fun capturePlayerView(): Bitmap? {
        return try {
            if (playerView.visibility != View.VISIBLE) {
                Log.w(TAG, "PlayerView not visible")
                return null
            }
            
            // Try to get TextureView from PlayerView
            val textureView = findTextureView(playerView)
            if (textureView != null) {
                Log.d(TAG, "Found TextureView, capturing from it")
                return captureFromTextureView(textureView)
            }
            
            // Get PlayerView dimensions
            val width = playerView.width
            val height = playerView.height
            
            if (width <= 0 || height <= 0) {
                Log.w(TAG, "PlayerView has invalid dimensions: ${width}x${height}")
                return null
            }
            
            // Create bitmap and canvas
            val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            val canvas = android.graphics.Canvas(bitmap)
            
            // Draw the view
            playerView.draw(canvas)
            
            bitmap
        } catch (e: Exception) {
            Log.e(TAG, "PlayerView capture failed", e)
            null
        }
    }
    
    /**
     * Find TextureView in PlayerView hierarchy
     */
    private fun findTextureView(view: View): android.view.TextureView? {
        if (view is android.view.TextureView) {
            return view
        }
        if (view is android.view.ViewGroup) {
            for (i in 0 until view.childCount) {
                val textureView = findTextureView(view.getChildAt(i))
                if (textureView != null) {
                    return textureView
                }
            }
        }
        return null
    }
    
    /**
     * Capture bitmap from TextureView
     */
    private fun captureFromTextureView(textureView: android.view.TextureView): Bitmap? {
        return try {
            Log.d(TAG, "Capturing from TextureView: ${textureView.width}x${textureView.height}")
            val bitmap = textureView.bitmap
            if (bitmap != null) {
                Log.d(TAG, "TextureView bitmap captured successfully")
            } else {
                Log.w(TAG, "TextureView bitmap is null")
            }
            bitmap
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get bitmap from TextureView", e)
            null
        }
    }
    
    /**
     * Modern screenshot capture using PixelCopy (Android 8.0+)
     * This properly captures video players and hardware-accelerated views
     */
    @androidx.annotation.RequiresApi(Build.VERSION_CODES.O)
    private suspend fun captureScreenWithPixelCopy(): Bitmap? = suspendCancellableCoroutine { continuation ->
        try {
            val rootView = window.decorView
            val width = rootView.width
            val height = rootView.height
            
            if (width <= 0 || height <= 0) {
                Log.e(TAG, "Invalid view dimensions: ${width}x${height}")
                continuation.resume(null)
                return@suspendCancellableCoroutine
            }
            
            val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            
            val locationInWindow = IntArray(2)
            rootView.getLocationInWindow(locationInWindow)
            
            val srcRect = android.graphics.Rect(0, 0, width, height)
            
            Log.d(TAG, "PixelCopy request: ${width}x${height}, location: ${locationInWindow[0]},${locationInWindow[1]}")
            
            PixelCopy.request(
                window,
                srcRect,
                bitmap,
                { copyResult ->
                    when (copyResult) {
                        PixelCopy.SUCCESS -> {
                            Log.d(TAG, "PixelCopy SUCCESS")
                            continuation.resume(bitmap)
                        }
                        PixelCopy.ERROR_SOURCE_NO_DATA -> {
                            Log.e(TAG, "PixelCopy ERROR_SOURCE_NO_DATA")
                            bitmap.recycle()
                            continuation.resume(null)
                        }
                        PixelCopy.ERROR_SOURCE_INVALID -> {
                            Log.e(TAG, "PixelCopy ERROR_SOURCE_INVALID")
                            bitmap.recycle()
                            continuation.resume(null)
                        }
                        PixelCopy.ERROR_DESTINATION_INVALID -> {
                            Log.e(TAG, "PixelCopy ERROR_DESTINATION_INVALID")
                            bitmap.recycle()
                            continuation.resume(null)
                        }
                        PixelCopy.ERROR_TIMEOUT -> {
                            Log.e(TAG, "PixelCopy ERROR_TIMEOUT")
                            bitmap.recycle()
                            continuation.resume(null)
                        }
                        else -> {
                            Log.e(TAG, "PixelCopy UNKNOWN_ERROR: $copyResult")
                            bitmap.recycle()
                            continuation.resume(null)
                        }
                    }
                },
                handler
            )
        } catch (e: Exception) {
            Log.e(TAG, "PixelCopy exception", e)
            continuation.resume(null)
        }
    }
    
    /**
     * Fallback screenshot capture for older Android versions
     */
    private fun captureScreenWithDrawingCache(): Bitmap? {
        return try {
            val rootView = window.decorView
            rootView.isDrawingCacheEnabled = true
            rootView.buildDrawingCache(true)
            
            val bitmap = if (rootView.drawingCache != null) {
                Bitmap.createBitmap(rootView.drawingCache)
            } else {
                // Alternative: manually draw
                val width = rootView.width
                val height = rootView.height
                val bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                val canvas = android.graphics.Canvas(bmp)
                rootView.draw(canvas)
                bmp
            }
            
            rootView.isDrawingCacheEnabled = false
            bitmap
        } catch (e: Exception) {
            Log.e(TAG, "Drawing cache capture failed", e)
            null
        }
    }

    override fun onResume() {
        super.onResume()
        if (currentPlaylist.isNotEmpty()) {
            player?.play()
        }
    }

    override fun onPause() {
        super.onPause()
        player?.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacksAndMessages(null)
        scope.cancel()
        layoutVideoPlayers.forEach { it.release() }
        layoutVideoPlayers.clear()
        player?.release()
    }

    // =========================================================================
    // Layout engine (full program layout driven from admin panel)
    // =========================================================================

    private fun renderProgramLayout(program: ProgramLayout) {
        layoutRoot.removeAllViews()
        layoutVideoPlayers.forEach { it.release() }
        layoutVideoPlayers.clear()

        player?.stop()
        playerView.visibility = View.GONE

        val rootWidth = layoutRoot.width.takeIf { it > 0 } ?: layoutRoot.measuredWidth
        val rootHeight = layoutRoot.height.takeIf { it > 0 } ?: layoutRoot.measuredHeight

        if (rootWidth == 0 || rootHeight == 0) {
            layoutRoot.post { renderProgramLayout(program) }
            return
        }

        val scaleX = rootWidth.toFloat() / program.width.toFloat().coerceAtLeast(1f)
        val scaleY = rootHeight.toFloat() / program.height.toFloat().coerceAtLeast(1f)

        var addedCount = 0
        for (element in program.elements.sortedBy { it.zIndex }) {
            val view = when (element.type) {
                "video" -> createVideoViewForElement(element)
                "image" -> createImageViewForElement(element)
                "text" -> createTextViewForElement(element)
                "webview" -> createWebViewForElement(element)
                else -> null
            } ?: continue

            val lp = FrameLayout.LayoutParams(
                (element.width * scaleX).toInt().coerceAtLeast(1),
                (element.height * scaleY).toInt().coerceAtLeast(1)
            )
            lp.leftMargin = (element.x * scaleX).toInt()
            lp.topMargin = (element.y * scaleY).toInt()

            layoutRoot.addView(view, lp)
            addedCount++
        }

        if (addedCount > 0) {
            showScreensaver(false)
        } else {
            Log.w(TAG, "Program ${program.id} has no renderable elements")
            showScreensaver(true)
        }
    }

    private fun createVideoViewForElement(element: LayoutElement): View? {
        val url = element.props.optString("url", "").takeIf { it.isNotBlank() } ?: return null
        return try {
            val exo = buildBufferedExoPlayer()
            layoutVideoPlayers.add(exo)

            val pv = PlayerView(this).apply {
                useController = false
                player = exo
            }

            exo.setMediaItem(MediaItem.fromUri(Uri.parse(url)))
            exo.repeatMode = Player.REPEAT_MODE_ALL
            exo.prepare()
            exo.playWhenReady = true
            pv
        } catch (e: Exception) {
            Log.e(TAG, "Failed to create video element: ${e.message}")
            null
        }
    }

    private fun createImageViewForElement(element: LayoutElement): View? {
        val url = element.props.optString("url", "").takeIf { it.isNotBlank() } ?: return null
        return try {
            val imageView = ImageView(this).apply {
                scaleType = ImageView.ScaleType.FIT_CENTER
            }
            val imageLoader = ImageLoader.Builder(this).build()
            val request = ImageRequest.Builder(this)
                .data(url)
                .target(imageView)
                .build()
            imageLoader.enqueue(request)
            imageView
        } catch (e: Exception) {
            Log.e(TAG, "Failed to create image element: ${e.message}")
            null
        }
    }

    private fun createTextViewForElement(element: LayoutElement): View {
        val content = element.props.optString("content", "")
        val fontSize = element.props.optInt("fontSize", 24)
        val color = element.props.optString("color", "#FFFFFF")
        val alignment = element.props.optString("alignment", "left")

        val tv = TextView(this).apply {
            text = content
            textSize = fontSize.toFloat()
            setTextColor(android.graphics.Color.parseColor(color))
        }

        when (alignment) {
            "center" -> tv.textAlignment = View.TEXT_ALIGNMENT_CENTER
            "right" -> tv.textAlignment = View.TEXT_ALIGNMENT_VIEW_END
            else -> tv.textAlignment = View.TEXT_ALIGNMENT_VIEW_START
        }

        return tv
    }

    private fun createWebViewForElement(element: LayoutElement): View? {
        val url = element.props.optString("url", "").takeIf { it.isNotBlank() } ?: return null
        return try {
            WebView(this).apply {
                settings.javaScriptEnabled = true
                webViewClient = WebViewClient()
                loadUrl(url)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to create webview element: ${e.message}")
            null
        }
    }
}
