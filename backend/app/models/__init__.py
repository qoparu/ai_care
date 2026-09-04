"""SQLAlchemy ORM models.

Layering (see docs/DATA_MODEL.md):
  raw_health_records  -> immutable-ish audit copy of whatever the collector sent
  normalized tables   -> typed, deduplicated records (sleep, hr, workouts, ...)
  daily_features      -> one row per local calendar day, deterministic derivation

Portability note: JSONB on PostgreSQL, JSON on SQLite (used by the test suite).
"""
from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date as SADate,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class RawHealthRecord(Base):
    """Verbatim source payload. Never rewritten by analytics."""

    __tablename__ = "raw_health_records"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_uid: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(Text, nullable=False)
    measured_at: Mapped[datetime | None] = mapped_column(TS)
    start_at: Mapped[datetime | None] = mapped_column(TS)
    end_at: Mapped[datetime | None] = mapped_column(TS)
    device_id: Mapped[str | None] = mapped_column(Text)
    source_package: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (UniqueConstraint("data_type", "source_uid", name="uq_raw_type_uid"),)


class SleepSession(Base):
    __tablename__ = "sleep_sessions"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_uid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Day the session is attributed to = LOCAL date of wake-up. See docs/DATA_MODEL.md.
    day: Mapped[Date] = mapped_column(SADate, index=True, nullable=False)
    sleep_start: Mapped[datetime] = mapped_column(TS, nullable=False)
    sleep_end: Mapped[datetime] = mapped_column(TS, nullable=False)
    duration_min: Mapped[float | None] = mapped_column(Float)
    actual_sleep_min: Mapped[float | None] = mapped_column(Float)
    awake_min: Mapped[float | None] = mapped_column(Float)
    rem_min: Mapped[float | None] = mapped_column(Float)
    light_min: Mapped[float | None] = mapped_column(Float)
    deep_min: Mapped[float | None] = mapped_column(Float)
    sleep_score: Mapped[float | None] = mapped_column(Float)
    sleep_efficiency: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    device_id: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class HeartRateSample(Base):
    __tablename__ = "heart_rate_samples"

    ts: Mapped[datetime] = mapped_column(TS, primary_key=True)
    device_id: Mapped[str] = mapped_column(Text, primary_key=True, default="unknown")
    bpm: Mapped[float] = mapped_column(Float, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DailyMetric(Base):
    """Daily scalars the watch/app already aggregates. NULL means 'not reported'."""

    __tablename__ = "daily_metrics"

    day: Mapped[Date] = mapped_column(SADate, primary_key=True)
    resting_hr: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    min_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    sleeping_hr: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float)
    hrv_sdnn_ms: Mapped[float | None] = mapped_column(Float)
    steps: Mapped[int | None] = mapped_column(Integer)
    active_kcal: Mapped[float | None] = mapped_column(Float)
    total_kcal: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    energy_score: Mapped[float | None] = mapped_column(Float)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_uid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    day: Mapped[Date] = mapped_column(SADate, index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    exercise_type: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    calories_kcal: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSONType)


class BodyMeasurement(Base):
    __tablename__ = "body_measurements"

    measured_at: Mapped[datetime] = mapped_column(TS, primary_key=True)
    day: Mapped[Date] = mapped_column(SADate, index=True, nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    skeletal_muscle_kg: Mapped[float | None] = mapped_column(Float)
    height_cm: Mapped[float | None] = mapped_column(Float)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSONType)


class CheckIn(Base):
    """Subjective self-report. The only data the watch cannot know."""

    __tablename__ = "checkins"

    day: Mapped[Date] = mapped_column(SADate, primary_key=True)
    energy: Mapped[int | None] = mapped_column(Integer)
    soreness: Mapped[int | None] = mapped_column(Integer)
    mood: Mapped[int | None] = mapped_column(Integer)
    stress: Mapped[int | None] = mapped_column(Integer)
    training_difficulty: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class DailyFeature(Base):
    """Deterministic derivation from the normalized tables. Safe to drop and rebuild."""

    __tablename__ = "daily_features"

    day: Mapped[Date] = mapped_column(SADate, primary_key=True)

    sleep_minutes: Mapped[float | None] = mapped_column(Float)
    sleep_efficiency: Mapped[float | None] = mapped_column(Float)
    deep_sleep_minutes: Mapped[float | None] = mapped_column(Float)
    rem_sleep_minutes: Mapped[float | None] = mapped_column(Float)
    light_sleep_minutes: Mapped[float | None] = mapped_column(Float)
    awake_minutes: Mapped[float | None] = mapped_column(Float)
    sleep_score: Mapped[float | None] = mapped_column(Float)
    sleep_debt_minutes: Mapped[float | None] = mapped_column(Float)
    bedtime_local_min: Mapped[float | None] = mapped_column(Float)
    waketime_local_min: Mapped[float | None] = mapped_column(Float)
    sleep_midpoint_local_min: Mapped[float | None] = mapped_column(Float)

    resting_hr: Mapped[float | None] = mapped_column(Float)
    avg_sleep_hr: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float)

    steps: Mapped[int | None] = mapped_column(Integer)
    active_calories: Mapped[float | None] = mapped_column(Float)
    workout_minutes: Mapped[float | None] = mapped_column(Float)
    workout_count: Mapped[int | None] = mapped_column(Integer)

    training_load: Mapped[float | None] = mapped_column(Float)
    acute_load_7d: Mapped[float | None] = mapped_column(Float)
    chronic_load_28d: Mapped[float | None] = mapped_column(Float)
    acwr: Mapped[float | None] = mapped_column(Float)

    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)

    hrv_zscore: Mapped[float | None] = mapped_column(Float)
    resting_hr_zscore: Mapped[float | None] = mapped_column(Float)
    sleep_zscore: Mapped[float | None] = mapped_column(Float)

    recovery_score: Mapped[float | None] = mapped_column(Float)
    readiness_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(8))

    # Full explainability blob: component scores, weights, contributions,
    # baselines used, confidence reasons, missing fields.
    explanation: Mapped[dict | None] = mapped_column(JSONType)
    missing_fields: Mapped[dict | None] = mapped_column(JSONType)

    calculated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


__all__ = [
    "Base",
    "RawHealthRecord",
    "SleepSession",
    "HeartRateSample",
    "DailyMetric",
    "Workout",
    "BodyMeasurement",
    "CheckIn",
    "DailyFeature",
]
