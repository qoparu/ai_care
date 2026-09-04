"""Pydantic v2 schemas.

These define the *ingestion contract* between the Android collector and the
backend. The Android app is free to change internally; this contract is not.
All timestamps MUST be timezone-aware (RFC3339 with offset). Naive datetimes
are rejected rather than silently assumed to be UTC or local.
"""
from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Aware = Annotated[datetime, Field()]


def _require_aware(v: datetime) -> datetime:
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError(
            "timestamp must be timezone-aware (RFC3339 with UTC offset, e.g. "
            "2026-09-03T23:41:00+05:00). Naive timestamps are ambiguous and rejected."
        )
    return v


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SleepSessionIn(_Base):
    source_uid: str
    start: datetime
    end: datetime
    duration_min: float | None = None
    actual_sleep_min: float | None = None
    awake_min: float | None = None
    rem_min: float | None = None
    light_min: float | None = None
    deep_min: float | None = None
    sleep_score: float | None = Field(default=None, ge=0, le=100)
    sleep_efficiency: float | None = Field(default=None, ge=0, le=100)
    avg_hr: float | None = Field(default=None, gt=0, lt=250)
    device_id: str | None = None
    raw: dict[str, Any] | None = None

    _v_start = field_validator("start")(_require_aware)
    _v_end = field_validator("end")(_require_aware)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: datetime, info):  # type: ignore[no-untyped-def]
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError("sleep end must be after start")
        return v


class HeartRateSampleIn(_Base):
    ts: datetime
    bpm: float = Field(gt=0, lt=300)
    device_id: str | None = None

    _v_ts = field_validator("ts")(_require_aware)


class DailyMetricIn(_Base):
    """One row per local calendar day, as reported by Samsung Health."""

    date: Date
    resting_hr: float | None = Field(default=None, gt=20, lt=200)
    avg_hr: float | None = Field(default=None, gt=20, lt=250)
    min_hr: float | None = Field(default=None, gt=20, lt=250)
    max_hr: float | None = Field(default=None, gt=20, lt=250)
    sleeping_hr: float | None = Field(default=None, gt=20, lt=200)
    hrv_rmssd_ms: float | None = Field(default=None, gt=0, lt=500)
    hrv_sdnn_ms: float | None = Field(default=None, gt=0, lt=500)
    steps: int | None = Field(default=None, ge=0, le=200_000)
    active_kcal: float | None = Field(default=None, ge=0, le=20_000)
    total_kcal: float | None = Field(default=None, ge=0, le=30_000)
    distance_m: float | None = Field(default=None, ge=0)
    energy_score: float | None = Field(default=None, ge=0, le=100)


class WorkoutIn(_Base):
    source_uid: str
    started_at: datetime
    ended_at: datetime | None = None
    exercise_type: str | None = None
    duration_sec: int | None = Field(default=None, ge=0, le=86_400)
    calories_kcal: float | None = Field(default=None, ge=0)
    avg_hr: float | None = Field(default=None, gt=0, lt=250)
    max_hr: float | None = Field(default=None, gt=0, lt=250)
    distance_m: float | None = Field(default=None, ge=0)
    raw: dict[str, Any] | None = None

    _v_started = field_validator("started_at")(_require_aware)

    @field_validator("ended_at")
    @classmethod
    def _v_ended(cls, v: datetime | None) -> datetime | None:
        return None if v is None else _require_aware(v)


class BodyMeasurementIn(_Base):
    measured_at: datetime
    weight_kg: float | None = Field(default=None, gt=10, lt=400)
    body_fat_pct: float | None = Field(default=None, ge=1, le=70)
    skeletal_muscle_kg: float | None = Field(default=None, gt=1, lt=100)
    height_cm: float | None = Field(default=None, gt=50, lt=250)
    raw: dict[str, Any] | None = None

    _v_measured = field_validator("measured_at")(_require_aware)


class IngestPayload(_Base):
    """The single payload the Android collector POSTs to /api/v1/ingest."""

    collector_version: str = "unknown"
    device_id: str | None = None
    source_package: str | None = "com.sec.android.app.shealth"
    timezone: str | None = None
    is_synthetic: bool = False

    sleep_sessions: list[SleepSessionIn] = Field(default_factory=list)
    heart_rate_samples: list[HeartRateSampleIn] = Field(default_factory=list)
    daily_metrics: list[DailyMetricIn] = Field(default_factory=list)
    workouts: list[WorkoutIn] = Field(default_factory=list)
    body_measurements: list[BodyMeasurementIn] = Field(default_factory=list)

    def record_count(self) -> int:
        return (
            len(self.sleep_sessions)
            + len(self.heart_rate_samples)
            + len(self.daily_metrics)
            + len(self.workouts)
            + len(self.body_measurements)
        )


class IngestResult(_Base):
    accepted: bool
    inserted: dict[str, int]
    updated: dict[str, int]
    rejected: list[str] = Field(default_factory=list)
    days_touched: list[Date] = Field(default_factory=list)
    features_recomputed: int = 0


class CheckInIn(_Base):
    date: Date
    energy: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    mood: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    training_difficulty: int | None = Field(default=None, ge=1, le=10)
    note: str | None = Field(default=None, max_length=1000)


class BaselineOut(_Base):
    metric: str
    n: int
    window_days: int
    median: float | None = None
    mad: float | None = None
    mean: float | None = None
    std: float | None = None
    p25: float | None = None
    p75: float | None = None
    confidence: Literal["LOW", "MEDIUM", "HIGH"]


class ContributionOut(_Base):
    component: str
    weight: float
    score: float
    contribution: float
    detail: str


class DailyReportOut(_Base):
    date: Date
    recovery_score: float | None
    readiness_score: float | None
    band: str | None
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    confidence_reasons: list[str]
    contributions: list[ContributionOut]
    features: dict[str, Any]
    deviations: dict[str, Any]
    missing_fields: list[str]
    deterministic_summary: str
    llm_summary: str | None = None
    llm_provider: str | None = None
    disclaimer: str = (
        "Wellness estimate derived from wearable data. Not a medical device, "
        "not a diagnosis."
    )
