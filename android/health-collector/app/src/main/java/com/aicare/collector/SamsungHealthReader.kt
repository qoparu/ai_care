package com.aicare.collector

/**
 * [HealthReader] implementation backed by the Samsung Health Data SDK
 * (package `com.samsung.android.sdk.health.data.*` — the current SDK, NOT the
 * deprecated `com.samsung.android.sdk.healthdata.*` one. Do not mix them.)
 *
 * STATUS: the store/permission/read plumbing below follows the API shape
 * confirmed from Samsung's own guide and API-reference pages (store creation,
 * permission requests, readDataRequestBuilder + LocalTimeFilter, readData()).
 * What is NOT verified here is the exact field layout of each returned
 * `HealthDataPoint` (e.g. which accessor gives sleep-stage minutes) — that
 * could not be checked because developer.samsung.com is unreachable from this
 * environment. Each mapping function below is marked with what to check in
 * Android Studio once the AAR is added: open HealthDataPoint in the decompiler
 * / autocomplete on `point.getValue(...)` and fix the TODOs against what you
 * actually see. That is a five-minute fix with the real SDK in hand; guessing
 * field names here would just be a more confident-looking wrong answer.
 *
 * Requires the AAR in app/libs/ (see app/libs/README.md) and developer mode
 * "Data read" enabled in Samsung Health on the test device.
 */

import android.content.Context
import com.samsung.android.sdk.health.data.HealthDataService
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.permission.AccessType
import com.samsung.android.sdk.health.data.permission.Permission
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.LocalTimeFilter
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId

/** Every permission this collector will ever ask for. Keep this list == the manifest. */
val REQUIRED_PERMISSIONS: Set<Permission> = setOf(
    Permission.of(DataTypes.SLEEP, AccessType.READ),
    Permission.of(DataTypes.HEART_RATE, AccessType.READ),
    Permission.of(DataTypes.STEPS, AccessType.READ),
    Permission.of(DataTypes.EXERCISE, AccessType.READ),
    // TODO verify these three data type names exist under this exact spelling —
    // confirmed present: SLEEP, HEART_RATE, STEPS, EXERCISE. Body composition /
    // HRV / active-calories constant names were not confirmed from here.
    // Check com.samsung.android.sdk.health.data.request.DataTypes in Android
    // Studio's autocomplete and correct these three if the names differ:
    Permission.of(DataTypes.BODY_COMPOSITION, AccessType.READ),
    Permission.of(DataTypes.ACTIVE_CALORIES_BURNED, AccessType.READ),
    Permission.of(DataTypes.HEART_RATE_VARIABILITY_RMSSD, AccessType.READ),
)

class SamsungHealthReader(context: Context) : HealthReader {

    private val store: HealthDataStore = HealthDataService.getStore(context.applicationContext)
    private val zone: ZoneId = ZoneId.systemDefault()

    /** Call from an Activity's onCreate/launcher before read() ever runs. */
    suspend fun ensurePermissions(activity: android.app.Activity): Boolean {
        val granted = store.getGrantedPermissions(REQUIRED_PERMISSIONS)
        if (granted.containsAll(REQUIRED_PERMISSIONS)) return true
        val result = store.requestPermissions(REQUIRED_PERMISSIONS, activity)
        return result.containsAll(REQUIRED_PERMISSIONS)
    }

    override suspend fun read(from: LocalDate, to: LocalDate): IngestPayload {
        val start = from.atStartOfDay()
        val end = LocalDateTime.of(to.plusDays(1), java.time.LocalTime.MIDNIGHT)
        val filter = LocalTimeFilter.of(start, end)

        val sleepPoints = readAll(DataTypes.SLEEP.readDataRequestBuilder.setLocalTimeFilter(filter).build())
        val exercisePoints = readAll(DataTypes.EXERCISE.readDataRequestBuilder.setLocalTimeFilter(filter).build())
        // Steps/HR/HRV/calories on Samsung Health are naturally daily-bucketed
        // for most watch data; if the SDK returns raw high-frequency points
        // instead, aggregate them into DailyMetricDto yourself before mapping —
        // do NOT send thousands of heart_rate_samples per day, the backend
        // accepts them but the ingestion contract expects daily summaries in
        // daily_metrics for HR/HRV/steps (see docs/INGESTION_CONTRACT.md).

        return IngestPayload(
            deviceId = android.os.Build.MODEL,
            timezone = zone.id,
            isSynthetic = false,
            sleepSessions = sleepPoints.mapNotNull { toSleepDto(it) },
            workouts = exercisePoints.mapNotNull { toWorkoutDto(it) },
            dailyMetrics = emptyList(), // TODO: fill in once daily HR/HRV/steps mapping is verified
            bodyMeasurements = emptyList(), // TODO: map DataTypes.BODY_COMPOSITION points
        )
    }

    private suspend fun readAll(request: Any): List<Any> {
        // TODO: the exact return type of healthDataStore.readData(request) and
        // its .dataList accessor could not be verified from here (confirmed to
        // exist per Samsung's docs, exact generic signature not confirmed).
        // Replace this stub with:
        //   val result = store.readData(request as ReadDataRequest<HealthDataPoint>)
        //   return result.dataList
        throw NotImplementedError(
            "Wire this to healthDataStore.readData(request).dataList once the AAR " +
                "is present — Android Studio autocomplete will show the exact " +
                "ReadDataRequest / ReadDataResponse generic signature."
        )
    }

    /**
     * TODO verify against the real HealthDataPoint for DataTypes.SLEEP:
     *   - stable identifier for sourceUid (Samsung docs mention a UID field on
     *     HealthDataPoint metadata — confirm the accessor name)
     *   - start/end instants -> convert to OffsetDateTime, NEVER LocalDateTime
     *     (the backend rejects naive timestamps — see Contract.kt)
     *   - stage durations (deep/rem/light/awake) — Samsung's own sleep-stage
     *     data type may be a separate associated data type rather than fields
     *     on the base SLEEP point; check
     *     DataTypes.SLEEP.associatedReadRequestBuilder if plain fields are
     *     insufficient (session mentioned "associated data" for sleep extras
     *     like skin temperature/oxygen — sleep stages may work the same way).
     */
    private fun toSleepDto(point: Any): SleepSessionDto? {
        throw NotImplementedError("map $point to SleepSessionDto — see TODO above")
    }

    /** TODO verify field accessors the same way as toSleepDto. */
    private fun toWorkoutDto(point: Any): WorkoutDto? {
        throw NotImplementedError("map $point to WorkoutDto — see TODO above")
    }

    companion object {
        /** [java.time.Instant] -> the contract's required timezone-aware string. */
        fun offset(instant: java.time.Instant, zone: ZoneId): String =
            OffsetDateTime.ofInstant(instant, zone).toString()
    }
}
