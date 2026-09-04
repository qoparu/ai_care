package com.aicare.collector

/**
 * Minimal debug UI: grant permissions, read the last 7 days, show the
 * normalized JSON on screen, upload it. This is the whole first-milestone
 * scope from the project brief — nothing more.
 *
 * The backend URL and bearer token below are debug-build placeholders. Before
 * this touches real data, move both into EncryptedSharedPreferences or a
 * gradle-level secrets file that is gitignored — never hardcode a production
 * token in source, per docs/METRICS.md's privacy section and the repo's
 * engineering rules.
 */

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import java.time.LocalDate

// TODO move to a gitignored secrets source before this ever runs against real data.
private const val DEBUG_BACKEND_URL = "http://10.0.2.2:8000"
private const val DEBUG_API_TOKEN = "change-me-dev-token"

class MainActivity : ComponentActivity() {

    private lateinit var reader: SamsungHealthReader
    private lateinit var uploader: Uploader

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        reader = SamsungHealthReader(this)
        uploader = Uploader(DEBUG_BACKEND_URL, tokenProvider = { DEBUG_API_TOKEN })

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    CollectorScreen(
                        onGrantPermissions = { onGrantPermissionsClicked() },
                        onSyncNow = { onSyncNowClicked() },
                    )
                }
            }
        }
    }

    private var statusText = mutableStateOf("Not started.")
    private var jsonText = mutableStateOf("")

    private fun onGrantPermissionsClicked() {
        lifecycleScope.launch {
            statusText.value = "Requesting permissions..."
            val ok = runCatching { reader.ensurePermissions(this@MainActivity) }
            statusText.value = ok.fold(
                onSuccess = { granted -> if (granted) "Permissions granted." else "Permissions denied." },
                onFailure = { e -> "Permission request failed: ${e.message}" },
            )
        }
    }

    private fun onSyncNowClicked() {
        lifecycleScope.launch {
            statusText.value = "Reading last 7 days..."
            val result = runCatching {
                val payload = reader.read(from = LocalDate.now().minusDays(6), to = LocalDate.now())
                val pretty = Json { prettyPrint = true; encodeDefaults = true; explicitNulls = false }
                jsonText.value = pretty.encodeToString(IngestPayload.serializer(), payload)
                payload
            }

            result.onFailure { e ->
                statusText.value = "Read failed: ${e.message}"
                return@launch
            }

            statusText.value = "Uploading..."
            when (val upload = uploader.upload(result.getOrThrow())) {
                is Uploader.Result.Ok -> statusText.value =
                    "Uploaded. Inserted: ${upload.body.inserted}, days: ${upload.body.daysTouched.size}"
                is Uploader.Result.Rejected -> statusText.value =
                    "Backend rejected it (HTTP ${upload.code}): ${upload.detail}"
                is Uploader.Result.Failed -> statusText.value =
                    "Upload failed: ${upload.cause.message}"
            }
        }
    }

    @Composable
    private fun CollectorScreen(onGrantPermissions: () -> Unit, onSyncNow: () -> Unit) {
        val status by statusText
        val json by jsonText
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Health Collector — debug build", style = MaterialTheme.typography.titleLarge)
            Button(onClick = onGrantPermissions) { Text("1. Grant permissions") }
            Button(onClick = onSyncNow) { Text("2. Sync last 7 days") }
            Text(status, style = MaterialTheme.typography.bodyMedium)
            if (json.isNotEmpty()) {
                Text("Payload sent:", style = MaterialTheme.typography.titleMedium)
                Text(json, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
