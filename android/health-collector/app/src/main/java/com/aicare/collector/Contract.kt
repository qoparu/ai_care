package com.aicare.collector

/**
 * Wire format for POST /api/v1/ingest.
 *
 * This file is the Kotlin mirror of backend/app/schemas.py. It is the one part
 * of the collector that is fully specified — the backend validates against it
 * strictly, rejects unknown fields, and rejects naive timestamps.
 *
 * Serialized field names must match the backend exactly (@SerialName where the
 * Kotlin name differs).
 *
 * STATUS: type definitions only. The Samsung Health / Health Connect reader
 * that populates these is not written yet.
 */

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class IngestPayload(
    @SerialName("collector_version") val collectorVersion: String = "android-collector/0.1.0",
    @SerialName("device_id") val deviceId: String? = null,
    @SerialName("source_package") val sourcePackage: String? = "com.sec.android.app.shealth",
    /** IANA zone name, e.g. "Asia/Almaty". */
    val timezone: String? = null,
    /** Must stay false for real data. The backend rejects true when DATA_PROFILE=prod. */
    @SerialName("is_synthetic") val isSynthetic: Boolean = false,

    @SerialName("sleep_sessions") val sleepSessions: List<SleepSessionDto> = emptyList(),
    @SerialName("heart_rate_samples") val heartRateSamples: List<HeartRateSampleDto> = emptyList(),
    @SerialName("daily_metrics") val dailyMetrics: List<DailyMetricDto> = emptyList(),
    val workouts: List<WorkoutDto> = emptyList(),
    @SerialName("body_measurements") val bodyMeasurements: List<BodyMeasurementDto> = emptyList(),
)

/**
 * All timestamps are RFC3339 WITH an offset: "2026-09-02T23:41:00+05:00".
 * Use OffsetDateTime.toString(), never LocalDateTime.toString().
 *
 * [sourceUid] must be stable across reads. Derive it from the source record's
 * own identifier — never from the read time, never from a random UUID.
 */
@Serializable
data class SleepSessionDto(
    @SerialName("source_uid") val sourceUid: String,
    val start: String,
    val end: String,
    @SerialName("duration_min") val durationMin: Double? = null,
    @SerialName("actual_sleep_min") val actualSleepMin: Double? = null,
    @SerialName("awake_min") val awakeMin: Double? = null,
    @SerialName("rem_min") val remMin: Double? = null,
    @SerialName("light_min") val lightMin: Double? = null,
    @SerialName("deep_min") val deepMin: Double? = null,
    @SerialName("sleep_score") val sleepScore: Double? = null,
    @SerialName("sleep_efficiency") val sleepEfficiency: Double? = null,
    @SerialName("avg_hr") val avgHr: Double? = null,
    @SerialName("device_id") val deviceId: String? = null,
)

@Serializable
data class HeartRateSampleDto(
    val ts: String,
    val bpm: Double,
    @SerialName("device_id") val deviceId: String? = null,
)

/**
 * One row per local calendar day.
 *
 * Every field is nullable on purpose: null means "the watch did not report
 * this", which is NOT the same as zero. Do not default anything to 0.0 to make
 * the JSON look tidy — that fabricates data and the analytics layer will
 * happily believe it.
 *
 * [hrvRmssdMs] is RMSSD in milliseconds. If the source exposes SDNN or a
 * proprietary index instead, do not put it here.
 */
@Serializable
data class DailyMetricDto(
    val date: String,                                        // "2026-09-03"
    @SerialName("resting_hr") val restingHr: Double? = null,
    @SerialName("avg_hr") val avgHr: Double? = null,
    @SerialName("min_hr") val minHr: Double? = null,
    @SerialName("max_hr") val maxHr: Double? = null,
    @SerialName("sleeping_hr") val sleepingHr: Double? = null,
    @SerialName("hrv_rmssd_ms") val hrvRmssdMs: Double? = null,
    @SerialName("hrv_sdnn_ms") val hrvSdnnMs: Double? = null,
    val steps: Int? = null,
    @SerialName("active_kcal") val activeKcal: Double? = null,
    @SerialName("total_kcal") val totalKcal: Double? = null,
    @SerialName("distance_m") val distanceM: Double? = null,
    @SerialName("energy_score") val energyScore: Double? = null,
)

@Serializable
data class WorkoutDto(
    @SerialName("source_uid") val sourceUid: String,
    @SerialName("started_at") val startedAt: String,
    @SerialName("ended_at") val endedAt: String? = null,
    /** Lowercase, underscored: "boxing", "strength", "running". See EXERCISE_INTENSITY_FALLBACK. */
    @SerialName("exercise_type") val exerciseType: String? = null,
    @SerialName("duration_sec") val durationSec: Int? = null,
    @SerialName("calories_kcal") val caloriesKcal: Double? = null,
    @SerialName("avg_hr") val avgHr: Double? = null,
    @SerialName("max_hr") val maxHr: Double? = null,
    @SerialName("distance_m") val distanceM: Double? = null,
)

@Serializable
data class BodyMeasurementDto(
    @SerialName("measured_at") val measuredAt: String,
    @SerialName("weight_kg") val weightKg: Double? = null,
    @SerialName("body_fat_pct") val bodyFatPct: Double? = null,
    @SerialName("skeletal_muscle_kg") val skeletalMuscleKg: Double? = null,
    @SerialName("height_cm") val heightCm: Double? = null,
)

@Serializable
data class IngestResult(
    val accepted: Boolean,
    val inserted: Map<String, Int> = emptyMap(),
    val updated: Map<String, Int> = emptyMap(),
    @SerialName("days_touched") val daysTouched: List<String> = emptyList(),
    @SerialName("features_recomputed") val featuresRecomputed: Int = 0,
)
