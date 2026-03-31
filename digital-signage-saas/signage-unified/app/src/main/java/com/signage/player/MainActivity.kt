package com.signage.player

import android.Manifest
import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.util.Base64
import android.util.Log
import android.view.PixelCopy
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.TextView
import android.widget.FrameLayout
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.core.content.ContextCompat
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
    private lateinit var notificationHeader: View
    private lateinit var connectionStatus: TextView
    private lateinit var closeButton: ImageButton
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
    private val hideHeaderRunnable = Runnable { hideNotificationHeader() }

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
        private const val DEFAULT_SERVER_URL = "https://benzos.uk/signage"
        private const val HEADER_HIDE_DELAY = 10000L
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        try {
            videoCache = VideoCache(this)

            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            window.addFlags(WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD)
            window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED)
            window.addFlags(WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
            window.addFlags(WindowManager.LayoutParams.FLAG_ALLOW_LOCK_WHILE_SCREEN_ON)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
                setShowWhenLocked(true)
                setTurnScreenOn(true)
            }

            setContentView(R.layout.activity_main)
            hideSystemUI()

            layoutRoot = findViewById(R.id.layout_root)
            playerView = findViewById(R.id.player_view)
            screensaverView = findViewById(R.id.screensaver_view)
            notificationHeader = findViewById(R.id.notification_header_container)
            connectionStatus = findViewById(R.id.connection_status)
            closeButton = findViewById(R.id.close_button)

            closeButton.setOnClickListener { unpinAndClose() }
            playerView.setOnClickListener { showNotificationHeader() }

            loadScreensaver()
        } catch (e: Exception) {
            Log.e(TAG, "Error in onCreate", e)
            Toast.makeText(this, "App initialization failed", Toast.LENGTH_LONG).show()
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

        if (connectionCode.isEmpty()) {
            showSetupScreen()
        } else {
            initializePlayer()
            startDeviceHeartbeat()
        }

        requestKioskPermissions()
        startWatchdogService()
    }

    private fun showNotificationHeader() {
        notificationHeader.visibility = View.VISIBLE
        handler.removeCallbacks(hideHeaderRunnable)
        handler.postDelayed(hideHeaderRunnable, HEADER_HIDE_DELAY)
    }

    private fun hideNotificationHeader() {
        notificationHeader.visibility = View.GONE
    }

    private fun unpinAndClose() {
        try {
            val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                if (am.lockTaskModeState != ActivityManager.LOCK_TASK_MODE_NONE) stopLockTask()
            } else {
                @Suppress("DEPRECATION")
                if (am.isInLockTaskMode) stopLockTask()
            }
        } catch (_: Exception) {}
        finish()
    }

    private fun requestKioskPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
            Toast.makeText(this, "Please allow 'Display over other apps' to ensure the player stays on top.", Toast.LENGTH_LONG).show()
            startActivity(intent)
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                try {
                    val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
                    startActivity(intent)
                } catch (e: Exception) {
                    Log.w(TAG, "Could not request battery optimization exemption")
                }
            }
        }

        if (!WatchdogService.hasUsageStatsPermission(this)) {
            val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
            Toast.makeText(this, "Please grant 'Usage access' for better auto-restart reliability.", Toast.LENGTH_LONG).show()
            startActivity(intent)
        }

        if (!isDefaultLauncher()) {
            Toast.makeText(this, "Tip: Set this app as your 'Home app' for 100% automatic operation.", Toast.LENGTH_LONG).show()
        }
    }

    private fun isDefaultLauncher(): Boolean {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        val res = packageManager.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
        return res != null && packageName == res.activityInfo.packageName
    }

    private fun startWatchdogService() {
        try {
            val intent = Intent(this, WatchdogService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start watchdog", e)
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
        notificationHeader = findViewById(R.id.notification_header_container)
        connectionStatus = findViewById(R.id.connection_status)
        closeButton = findViewById(R.id.close_button)
        connectionStatus.text = "Setup"
        closeButton.setOnClickListener { unpinAndClose() }

        val serverSection = findViewById<View>(R.id.server_section)
        val serverInput = findViewById<android.widget.EditText>(R.id.server_input)
        val codeInput = findViewById<android.widget.EditText>(R.id.connection_code_input)
        val connectButton = findViewById<android.widget.Button>(R.id.connect_button)
        val logoView = findViewById<ImageView>(R.id.logo_view)

        // Default server URL shown in the setup screen
        if (serverUrl.isEmpty()) {
            serverUrl = DEFAULT_SERVER_URL
        }
        serverSection?.visibility = View.VISIBLE
        serverInput.setText(serverUrl)
        if (connectionCode.isNotEmpty()) codeInput.setText(connectionCode)

        val imageLoader = ImageLoader.Builder(this).build()
        val request = ImageRequest.Builder(this).data(LOGO_URL).target(logoView).build()
        imageLoader.enqueue(request)

        connectButton.setOnClickListener {
            val code = codeInput.text.toString().trim().replace(Regex("[^0-9]"), "")
            if (code.length != 9) {
                Toast.makeText(this, "Enter 9-digit code", Toast.LENGTH_SHORT).show()
            } else {
                // Use the server URL from the input, or fall back to default
                val inputUrl = serverInput.text.toString().trim()
                serverUrl = if (inputUrl.isNotEmpty()) inputUrl else DEFAULT_SERVER_URL

                connectionCode = code
                getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putString(KEY_SERVER_URL, serverUrl)
                    .putString(KEY_CONNECTION_CODE, connectionCode)
                    .apply()
                apiClient.setBaseUrl(serverUrl)
                apiClient.setConnectionCode(connectionCode)
                testConnection()
            }
        }
    }

    private fun testConnection() {
        scope.launch {
            try {
                val status = withContext(Dispatchers.IO) { apiClient.getStatus() }
                if (!status.online) {
                    connectionStatus.text = "Server offline"
                    Toast.makeText(this@MainActivity, "Server offline", Toast.LENGTH_SHORT).show()
                    return@launch
                } else {
                    connectionStatus.text = "Connected"
                }
                withContext(Dispatchers.IO) {
                    apiClient.getPlaybackState(connectionCode, deviceId, deviceName)
                }

                Toast.makeText(this@MainActivity, "Connected!", Toast.LENGTH_SHORT).show()
                setContentView(R.layout.activity_main)
                layoutRoot = findViewById(R.id.layout_root)
                playerView = findViewById(R.id.player_view)
                screensaverView = findViewById(R.id.screensaver_view)
                notificationHeader = findViewById(R.id.notification_header_container)
                connectionStatus = findViewById(R.id.connection_status)
                closeButton = findViewById(R.id.close_button)
                closeButton.setOnClickListener { unpinAndClose() }
                playerView.setOnClickListener { showNotificationHeader() }
                hideSystemUI()
                loadScreensaver()
                initializePlayer()
                startDeviceHeartbeat()
                showNotificationHeader()
            } catch (e: Exception) {
                connectionStatus.text = "Connection failed"
                Toast.makeText(this@MainActivity, "Connection failed", Toast.LENGTH_LONG).show()
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
                        showScreensaver(playbackState == Player.STATE_IDLE)
                        if (playbackState == Player.STATE_ENDED) handler.post { playNextVideo() }
                    }
                })
            }
        } catch (e: Exception) {
            Log.e(TAG, "Player init error", e)
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

    private fun sendHeartbeatAndCheckCommands() {
        scope.launch {
            try {
                // First, try layout-based playback
                val layoutResponse = withContext(Dispatchers.IO) {
                    apiClient.setBaseUrl(serverUrl)
                    apiClient.setConnectionCode(connectionCode)
                    apiClient.getDeviceLayout(deviceId)
                }

                if (layoutResponse?.program != null && layoutResponse.program.elements.isNotEmpty()) {
                    connectionStatus.text = "Layout mode"
                    renderProgramLayout(layoutResponse.program)
                } else {
                    // Fallback to legacy playback state + playlist behavior
                    val playbackState = withContext(Dispatchers.IO) {
                        apiClient.getPlaybackState(connectionCode, deviceId, deviceName)
                    }
                    connectionStatus.text = "Connected"
                    if (playbackState.screenshot_requested == true) captureAndUploadScreenshot()
                    if (playbackState.command_id != lastCommandId) {
                        lastCommandId = playbackState.command_id
                        if (playbackState.current_video != null) {
                            playSpecificVideo(playbackState.current_video)
                        } else {
                            player?.stop()
                            showScreensaver(true)
                            currentPlaylist = emptyList()
                        }
                    } else if (currentPlaylist.isNotEmpty() || playbackState.current_video != null) {
                        updatePlaylist()
                    }
                }
            } catch (_: Exception) {
                connectionStatus.text = "Connection lost"
            }
        }
    }

    private fun playSpecificVideo(filename: String) {
        scope.launch {
            try {
                if (!videoCache.isCached(filename)) {
                    val videoData = withContext(Dispatchers.IO) { apiClient.downloadVideo(filename) }
                    videoCache.saveVideo(filename, videoData)
                }
                val cachedFile = videoCache.getCachedFile(filename)
                if (cachedFile?.exists() == true) {
                    showScreensaver(false)
                    player?.setMediaItem(MediaItem.fromUri(Uri.fromFile(cachedFile)))
                    player?.prepare()
                    player?.play()
                }
            } catch (_: Exception) {}
        }
    }

    private fun updatePlaylist() {
        scope.launch {
            try {
                val playlist = withContext(Dispatchers.IO) { apiClient.getPlaylist() }
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
                    currentPlaylist = playlist.videos
                    downloadVideos(playlist.videos)
                    if (player?.isPlaying != true && lastCommandId == -1) {
                        currentVideoIndex = 0
                        playCurrentVideo()
                    }
                }
            } catch (_: Exception) {}
        }
    }

    private fun downloadVideos(videos: List<Video>) {
        scope.launch(Dispatchers.IO) {
            videos.forEach { video ->
                try {
                    if (!videoCache.isCached(video.filename)) {
                        videoCache.saveVideo(video.filename, apiClient.downloadVideo(video.filename))
                    }
                } catch (_: Exception) {}
            }
        }
    }

    private fun playCurrentVideo() {
        if (currentPlaylist.isEmpty()) {
            showScreensaver(true)
            return
        }
        showScreensaver(false)
        val video = currentPlaylist[currentVideoIndex]
        val cachedFile = videoCache.getCachedFile(video.filename)
        if (cachedFile?.exists() == true) {
            player?.setMediaItem(MediaItem.fromUri(Uri.fromFile(cachedFile)))
            player?.prepare()
            player?.play()
        } else {
            handler.postDelayed({ playNextVideo() }, 1000)
        }
    }

    private fun playNextVideo() {
        if (currentPlaylist.isEmpty()) return
        currentVideoIndex++
        if (currentVideoIndex >= currentPlaylist.size) {
            if (playlistSettings.loop) {
                currentVideoIndex = 0
                playCurrentVideo()
            } else {
                showScreensaver(true)
            }
        } else {
            playCurrentVideo()
        }
    }

    private fun hideSystemUI() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.hide(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.navigationBars())
            window.insetsController?.systemBarsBehavior = android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_FULLSCREEN)
        }
    }

    private fun loadScreensaver() {
        val imageLoader = ImageLoader.Builder(this).components { add(SvgDecoder.Factory()) }.build()
        imageLoader.enqueue(ImageRequest.Builder(this).data(SCREENSAVER_URL).target(screensaverView).build())
    }

    private fun showScreensaver(show: Boolean) {
        screensaverView.visibility = if (show) View.VISIBLE else View.GONE
        playerView.visibility = if (show) View.GONE else View.VISIBLE
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemUI()
    }

    private fun captureAndUploadScreenshot() {
        scope.launch {
            try {
                val bitmap = withContext(Dispatchers.Main) {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) captureScreenWithPixelCopy()
                    else captureScreenWithDrawingCache()
                }
                if (bitmap != null) {
                    val base64 = withContext(Dispatchers.Default) {
                        val out = ByteArrayOutputStream()
                        bitmap.compress(Bitmap.CompressFormat.JPEG, 80, out)
                        bitmap.recycle()
                        "data:image/jpeg;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
                    }
                    withContext(Dispatchers.IO) { apiClient.uploadScreenshot(connectionCode, deviceId, base64) }
                }
            } catch (_: Exception) {}
        }
    }

    @androidx.annotation.RequiresApi(Build.VERSION_CODES.O)
    private suspend fun captureScreenWithPixelCopy(): Bitmap? = suspendCancellableCoroutine { cont ->
        try {
            val bmp = Bitmap.createBitmap(window.decorView.width, window.decorView.height, Bitmap.Config.ARGB_8888)
            PixelCopy.request(window, bmp, { if (it == PixelCopy.SUCCESS) cont.resume(bmp) else cont.resume(null) }, handler)
        } catch (_: Exception) { cont.resume(null) }
    }

    private fun captureScreenWithDrawingCache(): Bitmap? {
        return try {
            window.decorView.isDrawingCacheEnabled = true
            val bmp = Bitmap.createBitmap(window.decorView.drawingCache)
            window.decorView.isDrawingCacheEnabled = false
            bmp
        } catch (_: Exception) { null }
    }

    override fun onResume() {
        super.onResume()
        if (currentPlaylist.isNotEmpty()) player?.play()
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
    // Layout engine
    // =========================================================================

    private fun renderProgramLayout(program: ProgramLayout) {
        // Clear existing layout elements and players
        layoutRoot.removeAllViews()
        layoutVideoPlayers.forEach { it.release() }
        layoutVideoPlayers.clear()

        // When using layout mode, hide legacy full-screen player
        playerView.visibility = View.GONE

        val rootWidth = layoutRoot.width.takeIf { it > 0 } ?: layoutRoot.measuredWidth
        val rootHeight = layoutRoot.height.takeIf { it > 0 } ?: layoutRoot.measuredHeight

        if (rootWidth == 0 || rootHeight == 0) {
            // View not measured yet; post to layout pass
            layoutRoot.post { renderProgramLayout(program) }
            return
        }

        val scaleX = rootWidth.toFloat() / program.width.toFloat().coerceAtLeast(1f)
        val scaleY = rootHeight.toFloat() / program.height.toFloat().coerceAtLeast(1f)

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
        }

        showScreensaver(false)
    }

    private fun createVideoViewForElement(element: LayoutElement): View? {
        val url = element.props.optString("url", null) ?: return null
        val exo = ExoPlayer.Builder(this).build()
        layoutVideoPlayers.add(exo)

        val pv = PlayerView(this).apply {
            useController = false
            player = exo
        }

        val mediaItem = MediaItem.fromUri(Uri.parse(url))
        exo.setMediaItem(mediaItem)
        exo.repeatMode = Player.REPEAT_MODE_ALL
        exo.prepare()
        exo.playWhenReady = true

        return pv
    }

    private fun createImageViewForElement(element: LayoutElement): View? {
        val url = element.props.optString("url", null) ?: return null
        val imageView = ImageView(this).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER
        }
        val imageLoader = ImageLoader.Builder(this).build()
        val request = ImageRequest.Builder(this)
            .data(url)
            .target(imageView)
            .build()
        imageLoader.enqueue(request)
        return imageView
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
        val url = element.props.optString("url", null) ?: return null
        val webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            webViewClient = WebViewClient()
            loadUrl(url)
        }
        return webView
    }
}
