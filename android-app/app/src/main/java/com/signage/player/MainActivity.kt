package com.signage.player

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Base64
import android.util.Log
import android.view.PixelCopy
import android.view.View
import android.view.WindowManager
import android.widget.ImageView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import coil.ImageLoader
import coil.decode.SvgDecoder
import coil.request.ImageRequest
import kotlinx.coroutines.*
import java.io.ByteArrayOutputStream
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine

class MainActivity : AppCompatActivity() {

    private lateinit var playerView: PlayerView
    private lateinit var screensaverView: ImageView
    private var player: ExoPlayer? = null
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

    companion object {
        private const val TAG = "SignagePlayer"
        private const val PREFS_NAME = "SignagePrefs"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_CONNECTION_CODE = "connection_code"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_DEVICE_NAME = "device_name"
        private const val UPDATE_INTERVAL = 3000L
        private const val SCREENSAVER_URL = "https://karchershop.ge/cdn/shop/files/logo_karcher_2015.svg?v=1683099671&width=600"
        private const val LOGO_URL = "https://images.seeklogo.com/logo-png/43/2/karcher-logo-png_seeklogo-437949.png"
        /** Default server URL – no server input needed; user only enters 9-digit code */
        private const val DEFAULT_SERVER_URL = "https://digitalsignage-gits.onrender.com"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        try {
            videoCache = VideoCache(this)
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            setContentView(R.layout.activity_main)
            hideSystemUI()

            playerView = findViewById(R.id.player_view)
            screensaverView = findViewById(R.id.screensaver_view)

            loadScreensaver()
        } catch (e: Exception) {
            Log.e(TAG, "Error in onCreate", e)
            Toast.makeText(this, "App initialization failed: ${e.message}", Toast.LENGTH_LONG).show()
            return
        }

        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        serverUrl = prefs.getString(KEY_SERVER_URL, "") ?: ""
        if (serverUrl.isEmpty()) serverUrl = DEFAULT_SERVER_URL
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
            startDeviceHeartbeat()
        }
    }

    private fun generateDeviceId(): String {
        var androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        if (androidId == null || androidId == "9774d56d682e549c") {
            androidId = "android_${System.currentTimeMillis()}"
        }
        return "android_$androidId"
    }

    private fun showSetupScreen() {
        setContentView(R.layout.activity_setup)
        val codeInput = findViewById<android.widget.EditText>(R.id.connection_code_input)
        val connectButton = findViewById<android.widget.Button>(R.id.connect_button)
        val logoView = findViewById<ImageView>(R.id.logo_view)

        serverUrl = DEFAULT_SERVER_URL
        if (connectionCode.isNotEmpty()) codeInput.setText(connectionCode)

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
                    connectionCode = code
                    getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                        .edit()
                        .putString(KEY_SERVER_URL, serverUrl)
                        .putString(KEY_CONNECTION_CODE, connectionCode)
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
                // Validate 9-digit code with playback state (throws if code invalid)
                withContext(Dispatchers.IO) {
                    apiClient.getPlaybackState(connectionCode, deviceId, deviceName)
                }

                Toast.makeText(this@MainActivity, "Connected successfully!", Toast.LENGTH_SHORT).show()

                    setContentView(R.layout.activity_main)
                    playerView = findViewById(R.id.player_view)
                    screensaverView = findViewById(R.id.screensaver_view)
                    hideSystemUI()
                    loadScreensaver()

                    initializePlayer()
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

    private fun initializePlayer() {
        try {
            player = ExoPlayer.Builder(this).build().also { exoPlayer ->
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
     * FIXED: Send heartbeat and check commands - Format now works correctly!
     */
    private fun sendHeartbeatAndCheckCommands() {
        scope.launch {
            try {
                val playbackState = withContext(Dispatchers.IO) {
                    apiClient.getPlaybackState(connectionCode, deviceId, deviceName)
                }

                Log.d(TAG, "Heartbeat sent. Command ID: ${playbackState.command_id}, Current video: ${playbackState.current_video}")

                // Update device name from server if provided
                if (!playbackState.device_name.isNullOrEmpty() && playbackState.device_name != deviceName) {
                    Log.d(TAG, "📝 Server updated device name: $deviceName → ${playbackState.device_name}")
                    deviceName = playbackState.device_name
                    // Save to preferences
                    getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                        .edit()
                        .putString(KEY_DEVICE_NAME, deviceName)
                        .apply()
                }

                // Handle screenshot request
                if (playbackState.screenshot_requested == true) {
                    Log.d(TAG, "📸 Screenshot requested by server")
                    captureAndUploadScreenshot()
                }

                if (playbackState.command_id != lastCommandId) {
                    Log.d(TAG, "New command received! Previous: $lastCommandId, New: ${playbackState.command_id}")
                    lastCommandId = playbackState.command_id

                    if (playbackState.current_video != null) {
                        Log.d(TAG, "Server commanded to play: ${playbackState.current_video}")
                        playSpecificVideo(playbackState.current_video)
                    } else {
                        // FIXED: Format/stop command - don't restart videos!
                        Log.d(TAG, "Stop/format command received - stopping all playback")
                        
                        player?.stop()
                        showScreensaver(true)
                        clearVideoCache()
                        
                        // Clear playlist to prevent auto-play
                        currentPlaylist = emptyList()
                        currentVideoIndex = 0
                        
                        // DON'T call updatePlaylist() - this was restarting videos!
                        Log.d(TAG, "Playback stopped, cache cleared, waiting for new command")
                    }
                } else {
                    // No new command - only update if not stopped
                    if (currentPlaylist.isNotEmpty() || playbackState.current_video != null) {
                        updatePlaylist()
                    }
                }

            } catch (e: Exception) {
                Log.e(TAG, "Heartbeat failed", e)
                showScreensaver(true)
            }
        }
    }

    private fun clearVideoCache() {
        scope.launch(Dispatchers.IO) {
            try {
                val cacheSize = videoCache.getCacheSize()
                videoCache.clearCache()
                
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

    private fun playSpecificVideo(filename: String) {
        scope.launch {
            try {
                if (!videoCache.isCached(filename)) {
                    Log.d(TAG, "Video not cached, downloading: $filename")
                    val videoData = withContext(Dispatchers.IO) {
                        apiClient.downloadVideo(filename)
                    }
                    videoCache.saveVideo(filename, videoData)
                }

                val cachedFile = videoCache.getCachedFile(filename)
                if (cachedFile != null && cachedFile.exists()) {
                    showScreensaver(false)
                    val mediaItem = MediaItem.fromUri(Uri.fromFile(cachedFile))
                    player?.apply {
                        setMediaItem(mediaItem)
                        prepare()
                        play()
                    }
                    Log.d(TAG, "Playing commanded video: $filename")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to play commanded video: $filename", e)
            }
        }
    }

    private fun updatePlaylist() {
        scope.launch {
            try {
                val playlist = withContext(Dispatchers.IO) {
                    apiClient.getPlaylist()
                }

                playlistSettings = playlist.settings

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
                    downloadVideos(playlist.videos)

                    if (player?.isPlaying != true && lastCommandId == -1) {
                        currentVideoIndex = 0
                        playCurrentVideo()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to update playlist", e)
            }
        }
    }

    private fun downloadVideos(videos: List<Video>) {
        scope.launch(Dispatchers.IO) {
            videos.forEach { video ->
                try {
                    if (!videoCache.isCached(video.filename)) {
                        Log.d(TAG, "Downloading: ${video.filename}")
                        val videoData = apiClient.downloadVideo(video.filename)
                        videoCache.saveVideo(video.filename, videoData)
                        Log.d(TAG, "Downloaded: ${video.filename}")
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to download ${video.filename}", e)
                }
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
        val cachedFile = videoCache.getCachedFile(video.filename)

        if (cachedFile != null && cachedFile.exists()) {
            val mediaItem = MediaItem.fromUri(Uri.fromFile(cachedFile))
            player?.apply {
                setMediaItem(mediaItem)
                prepare()
                play()
            }

            Log.d(TAG, "Playing: ${video.name} (${currentVideoIndex + 1}/${currentPlaylist.size})")
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
        player?.release()
    }
}
