"""Ingestion: raw preservation + idempotent normalization.

Idempotency is by `source_uid`, so the collector can re-send an overlapping
window as many times as it likes without creating duplicates.
"""
from __future__ import annotations

import logging
from datetime import date as Date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.analytics.features import local_date
from app.schemas import IngestPayload, IngestResult

log = logging.getLogger(__name__)


def _store_raw(
    db: Session,
    *,
    data_type: str,
    source_uid: str | None,
    payload: dict,
    device_id: str | None,
    source_package: str | None,
    is_synthetic: bool,
    measured_at=None,
    start_at=None,
    end_at=None,
) -> None:
    existing = None
    if source_uid is not None:
        existing = db.execute(
            select(models.RawHealthRecord).where(
                models.RawHealthRecord.data_type == data_type,
                models.RawHealthRecord.source_uid == source_uid,
            )
        ).scalar_one_or_none()
    if existing is not None:
        existing.payload = payload
        return
    db.add(
        models.RawHealthRecord(
            data_type=data_type,
            source_uid=source_uid,
            payload=payload,
            device_id=device_id,
            source_package=source_package,
            is_synthetic=is_synthetic,
            measured_at=measured_at,
            start_at=start_at,
            end_at=end_at,
        )
    )


def ingest(db: Session, payload: IngestPayload, *, tz: str) -> IngestResult:
    inserted: dict[str, int] = {}
    updated: dict[str, int] = {}
    days: set[Date] = set()
    syn = payload.is_synthetic

    def bump(d: dict[str, int], k: str) -> None:
        d[k] = d.get(k, 0) + 1

    # --- sleep -----------------------------------------------------------
    for s in payload.sleep_sessions:
        day = local_date(s.end, tz)  # attribution: wake-up day
        days.add(day)
        _store_raw(
            db,
            data_type="sleep",
            source_uid=s.source_uid,
            payload=s.model_dump(mode="json"),
            device_id=s.device_id or payload.device_id,
            source_package=payload.source_package,
            is_synthetic=syn,
            start_at=s.start,
            end_at=s.end,
        )
        row = db.execute(
            select(models.SleepSession).where(models.SleepSession.source_uid == s.source_uid)
        ).scalar_one_or_none()
        duration = s.duration_min
        if duration is None:
            duration = (s.end - s.start).total_seconds() / 60.0
        fields = dict(
            day=day,
            sleep_start=s.start,
            sleep_end=s.end,
            duration_min=duration,
            actual_sleep_min=s.actual_sleep_min,
            awake_min=s.awake_min,
            rem_min=s.rem_min,
            light_min=s.light_min,
            deep_min=s.deep_min,
            sleep_score=s.sleep_score,
            sleep_efficiency=s.sleep_efficiency,
            avg_hr=s.avg_hr,
            device_id=s.device_id or payload.device_id,
            is_synthetic=syn,
        )
        if row is None:
            db.add(models.SleepSession(source_uid=s.source_uid, **fields))
            bump(inserted, "sleep_sessions")
        else:
            for k, val in fields.items():
                setattr(row, k, val)
            bump(updated, "sleep_sessions")

    # --- heart rate samples ----------------------------------------------
    for h in payload.heart_rate_samples:
        dev = h.device_id or payload.device_id or "unknown"
        days.add(local_date(h.ts, tz))
        row = db.get(models.HeartRateSample, {"ts": h.ts, "device_id": dev})
        if row is None:
            db.add(models.HeartRateSample(ts=h.ts, device_id=dev, bpm=h.bpm, is_synthetic=syn))
            bump(inserted, "heart_rate_samples")
        else:
            row.bpm = h.bpm
            bump(updated, "heart_rate_samples")

    # --- daily metrics ----------------------------------------------------
    for m in payload.daily_metrics:
        days.add(m.date)
        _store_raw(
            db,
            data_type="daily_metric",
            source_uid=f"daily:{m.date.isoformat()}",
            payload=m.model_dump(mode="json"),
            device_id=payload.device_id,
            source_package=payload.source_package,
            is_synthetic=syn,
        )
        row = db.get(models.DailyMetric, m.date)
        data = m.model_dump(exclude={"date"})
        if row is None:
            db.add(models.DailyMetric(day=m.date, is_synthetic=syn, **data))
            bump(inserted, "daily_metrics")
        else:
            # Partial updates must not wipe previously known values.
            for k, val in data.items():
                if val is not None:
                    setattr(row, k, val)
            bump(updated, "daily_metrics")

    # --- workouts ---------------------------------------------------------
    for w in payload.workouts:
        day = local_date(w.started_at, tz)
        days.add(day)
        _store_raw(
            db,
            data_type="workout",
            source_uid=w.source_uid,
            payload=w.model_dump(mode="json"),
            device_id=payload.device_id,
            source_package=payload.source_package,
            is_synthetic=syn,
            start_at=w.started_at,
            end_at=w.ended_at,
        )
        row = db.execute(
            select(models.Workout).where(models.Workout.source_uid == w.source_uid)
        ).scalar_one_or_none()
        duration = w.duration_sec
        if duration is None and w.ended_at is not None:
            duration = int((w.ended_at - w.started_at).total_seconds())
        fields = dict(
            day=day,
            started_at=w.started_at,
            ended_at=w.ended_at,
            exercise_type=w.exercise_type,
            duration_sec=duration,
            calories_kcal=w.calories_kcal,
            avg_hr=w.avg_hr,
            max_hr=w.max_hr,
            distance_m=w.distance_m,
            is_synthetic=syn,
            raw=w.raw,
        )
        if row is None:
            db.add(models.Workout(source_uid=w.source_uid, **fields))
            bump(inserted, "workouts")
        else:
            for k, val in fields.items():
                setattr(row, k, val)
            bump(updated, "workouts")

    # --- body -------------------------------------------------------------
    for b in payload.body_measurements:
        day = local_date(b.measured_at, tz)
        days.add(day)
        row = db.get(models.BodyMeasurement, b.measured_at)
        fields = dict(
            day=day,
            weight_kg=b.weight_kg,
            body_fat_pct=b.body_fat_pct,
            skeletal_muscle_kg=b.skeletal_muscle_kg,
            height_cm=b.height_cm,
            is_synthetic=syn,
            raw=b.raw,
        )
        if row is None:
            db.add(models.BodyMeasurement(measured_at=b.measured_at, **fields))
            bump(inserted, "body_measurements")
        else:
            for k, val in fields.items():
                setattr(row, k, val)
            bump(updated, "body_measurements")

    db.flush()
    # NOTE: counts only. Never log health values themselves.
    log.info(
        "ingest: %d records, %d days touched, synthetic=%s",
        payload.record_count(),
        len(days),
        syn,
    )
    return IngestResult(
        accepted=True,
        inserted=inserted,
        updated=updated,
        days_touched=sorted(days),
    )
