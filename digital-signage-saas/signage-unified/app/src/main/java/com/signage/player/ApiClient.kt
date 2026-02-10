package com.signage.player

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class Video(
    val filename: String,
    val name: String,
    val url: String
)

data class PlaylistSettings(
    val interval: Int = 30,
    val loop: Boolean = true
)

data class Playlist(
    val videos: List<Video>,
    val settings: PlaylistSettings
)

data class PlaybackState(
    val current_video: String?,
    val mode: String,
    val command_id: Int,
    val screenshot_requested: Boolean? = false,
    val clear_cache: Boolean? = false,
    val device_name: String? = null  // Server's name for this device
)

data class ServerStatus(
    val online: Boolean,
    val video_count: Int = 0,
    val connected_devices: Int = 0
)

class ApiClient {
    private var baseUrl = ""
    private var connectionCode = ""
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    companion object {
        private const val TAG = "ApiClient"
    }

    fun setBaseUrl(url: String) {
        baseUrl = url.trimEnd('/')
        Log.d(TAG, "API base URL set to: $baseUrl")
    }

    fun setConnectionCode(code: String) {
        connectionCode = code.trim()
        Log.d(TAG, "Connection code set: ${if (connectionCode.isEmpty()) "none" else "***${connectionCode.takeLast(3)}"}")
    }

    suspend fun getStatus(): ServerStatus = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/api/status")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("Unexpected code $response")

            val json = JSONObject(response.body!!.string())
            ServerStatus(
                online = json.optBoolean("online", false),
                video_count = json.optInt("video_count", 0),
                connected_devices = json.optInt("connected_devices", 0)
            )
        }
    }

    suspend fun getPlaybackState(connectionCode: String, deviceId: String, deviceName: String): PlaybackState = 
        withContext(Dispatchers.IO) {
            val codeParam = if (connectionCode.isNotEmpty()) "code=${connectionCode}" else ""
            val deviceParams = "device_id=${deviceId}&device_name=${deviceName}"
            val url = "$baseUrl/api/playback/state?$deviceParams${if (codeParam.isNotEmpty()) "&$codeParam" else ""}"
            val request = Request.Builder()
                .url(url)
                .get()
                .build()

            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) throw IOException("Unexpected code $response")

                val json = JSONObject(response.body!!.string())
                PlaybackState(
                    current_video = if (json.isNull("current_video")) null else json.getString("current_video"),
                    mode = json.optString("mode", "manual"),
                    command_id = json.optInt("command_id", 0),
                    screenshot_requested = json.optBoolean("screenshot_requested", false),
                    clear_cache = json.optBoolean("clear_cache", false),
                    device_name = json.optString("device_name", null)
                )
            }
        }

    suspend fun getPlaylist(): Playlist = withContext(Dispatchers.IO) {
        val url = if (connectionCode.isNotEmpty()) {
            "$baseUrl/api/playlist?code=$connectionCode"
        } else {
            "$baseUrl/api/playlist"
        }
        val request = Request.Builder()
            .url(url)
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("Unexpected code $response")

            val json = JSONObject(response.body!!.string())
            val videosArray = json.getJSONArray("videos")
            val settingsJson = json.getJSONObject("settings")

            val videos = mutableListOf<Video>()
            for (i in 0 until videosArray.length()) {
                val videoJson = videosArray.getJSONObject(i)
                videos.add(
                    Video(
                        filename = videoJson.getString("filename"),
                        name = videoJson.getString("name"),
                        url = videoJson.getString("url")
                    )
                )
            }

            Playlist(
                videos = videos,
                settings = PlaylistSettings(
                    interval = settingsJson.optInt("interval", 30),
                    loop = settingsJson.optBoolean("loop", true)
                )
            )
        }
    }

    suspend fun downloadVideo(filename: String): ByteArray = withContext(Dispatchers.IO) {
        val url = if (connectionCode.isNotEmpty()) {
            "$baseUrl/api/video/$filename?code=$connectionCode"
        } else {
            "$baseUrl/api/video/$filename"
        }
        val request = Request.Builder()
            .url(url)
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("Unexpected code $response")
            response.body!!.bytes()
        }
    }

    /**
     * Upload screenshot to server
     */
    suspend fun uploadScreenshot(connectionCode: String, deviceId: String, screenshotBase64: String) = 
        withContext(Dispatchers.IO) {
            try {
                val codeParam = if (connectionCode.isNotEmpty()) "?code=$connectionCode" else ""
                val url = "$baseUrl/api/devices/$deviceId/screenshot/upload$codeParam"
                
                val json = JSONObject()
                json.put("screenshot", screenshotBase64)
                
                val mediaType = "application/json; charset=utf-8".toMediaType()
                val requestBody = json.toString().toRequestBody(mediaType)
                
                val request = Request.Builder()
                    .url(url)
                    .post(requestBody)
                    .build()

                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        throw IOException("Screenshot upload failed: ${response.code}")
                    }
                    Log.d(TAG, "Screenshot uploaded successfully")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to upload screenshot", e)
                throw e
            }
        }
}
