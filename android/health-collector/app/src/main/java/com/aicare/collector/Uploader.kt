package com.aicare.collector

/**
 * Uploads a normalized payload to the analytics backend.
 *
 * STATUS: written but never run on a device.
 *
 * The API token belongs in EncryptedSharedPreferences or the Android Keystore —
 * never in source, never in BuildConfig committed to git, never in a log line.
 */

import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

class Uploader(
    private val baseUrl: String,
    private val tokenProvider: () -> String,
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build(),
) {
    private val json = Json { encodeDefaults = true; explicitNulls = false }
    private val mediaType = "application/json; charset=utf-8".toMediaType()

    sealed interface Result {
        data class Ok(val body: IngestResult) : Result
        /** 422 means the payload violated the contract. Read [detail] — it says which field. */
        data class Rejected(val code: Int, val detail: String) : Result
        data class Failed(val cause: Throwable) : Result
    }

    fun upload(payload: IngestPayload): Result {
        val body = json.encodeToString(IngestPayload.serializer(), payload).toRequestBody(mediaType)
        val request = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/api/v1/ingest")
            .addHeader("Authorization", "Bearer ${tokenProvider()}")
            .post(body)
            .build()

        return try {
            client.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (response.isSuccessful) {
                    Result.Ok(json.decodeFromString(IngestResult.serializer(), text))
                } else {
                    // Do not log `text` in production: an error echo can contain health values.
                    Result.Rejected(response.code, text.take(500))
                }
            }
        } catch (t: Throwable) {
            Result.Failed(t)
        }
    }
}
