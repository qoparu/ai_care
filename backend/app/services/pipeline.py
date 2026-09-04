"""Feature -> baseline -> score pipeline.

Deterministic and idempotent: rebuilding a date range from the normalized
tables always produces the same daily_features rows. There is no incremental
state to corrupt - if anything looks wrong, drop daily_features and rebuild.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.analytics.baseline import Baseline, compute_baseline, ewma
from app.analytics.confidence import assess_confidence
from app.analytics.features import DayInputs, compute_day_features, merge_sleep_sessions, sleep_debt
from app.analytics.recovery import compute_recovery
from app.config import Settings

log = logging.getLogger(__name__)

BASELINE_METRICS = (
    "hrv_rmssd_ms",
    "resting_hr",
    "sleep_minutes",
    "sleep_efficiency",
    "training_load",
    "steps",
    "sleep_midpoint_local_min",
)


def _row_to_dict(obj) -> dict:  # type: ignore[no-untyped-def]
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def data_date_range(db: Session) -> tuple[Date | None, Date | None]:
    """Earliest and latest day for which any normalized data exists."""
    lo: Date | None = None
    hi: Date | None = None
    for col, model in (
        (models.SleepSession.day, models.SleepSession),
        (models.DailyMetric.day, models.DailyMetric),
        (models.Workout.day, models.Workout),
        (models.BodyMeasurement.day, models.BodyMeasurement),
    ):
        a, b = db.execute(select(func.min(col), func.max(col))).one()
        if a is not None:
            lo = a if lo is None else min(lo, a)
        if b is not None:
            hi = b if hi is None else max(hi, b)
    return lo, hi


def collect_day_inputs(db: Session, start: Date, end: Date) -> dict[Date, DayInputs]:
    days: dict[Date, DayInputs] = {}
    d = start
    while d <= end:
        days[d] = DayInputs(day=d)
        d += timedelta(days=1)

    sleeps: dict[Date, list[dict]] = {}
    for s in db.execute(
        select(models.SleepSession).where(
            models.SleepSession.day >= start, models.SleepSession.day <= end
        )
    ).scalars():
        sleeps.setdefault(s.day, []).append(_row_to_dict(s))
    for day, group in sleeps.items():
        if day in days:
            days[day].sleep = merge_sleep_sessions(group)

    for m in db.execute(
        select(models.DailyMetric).where(models.DailyMetric.day >= start, models.DailyMetric.day <= end)
    ).scalars():
        if m.day in days:
            days[m.day].metrics = _row_to_dict(m)
            days[m.day].activity_synced = True

    for w in db.execute(
        select(models.Workout).where(models.Workout.day >= start, models.Workout.day <= end)
    ).scalars():
        if w.day in days:
            days[w.day].workouts.append(_row_to_dict(w))
            days[w.day].activity_synced = True

    for b in db.execute(
        select(models.BodyMeasurement).where(
            models.BodyMeasurement.day >= start, models.BodyMeasurement.day <= end
        )
    ).scalars():
        if b.day in days:
            days[b.day].body = _row_to_dict(b)

    for day, di in days.items():
        if di.sleep is not None:
            di.activity_synced = di.activity_synced or False
    return days


def rebuild(db: Session, settings: Settings, start: Date | None = None, end: Date | None = None) -> int:
    """Recompute daily_features for [start, end]. Returns rows written.

    Baselines are trailing, so the window is silently extended backwards by
    `baseline_window_days` to give the first requested day a real baseline.
    """
    lo, hi = data_date_range(db)
    if lo is None or hi is None:
        return 0
    start = start or lo
    end = end or hi
    load_start = min(start, lo) - timedelta(days=settings.baseline_window_days + 1)
    inputs = collect_day_inputs(db, max(lo - timedelta(days=1), load_start), end)

    tz = settings.timezone
    hr_max = settings.hr_max()

    # Pass 1: raw per-day features, independent of history.
    feats: dict[Date, dict] = {}
    missing_map: dict[Date, list[str]] = {}
    for day in sorted(inputs):
        f = compute_day_features(
            inputs[day],
            tz=tz,
            sex=settings.sex,
            hr_max=hr_max,
        )
        feats[day] = f.values
        missing_map[day] = f.missing

    ordered_days = sorted(feats)
    series: dict[str, dict[Date, float | None]] = {
        metric: {d: _num(feats[d].get(metric)) for d in ordered_days} for metric in BASELINE_METRICS
    }

    # Pass 2: history-dependent features + scores.
    checkins = {
        c.day: _row_to_dict(c)
        for c in db.execute(select(models.CheckIn).where(models.CheckIn.day >= start - timedelta(days=1))).scalars()
    }

    written = 0
    for day in ordered_days:
        if day < start or day > end:
            continue
        vals = feats[day]

        baselines: dict[str, Baseline] = {
            m: compute_baseline(
                m,
                series[m],
                as_of=day,
                window_days=settings.baseline_window_days,
                min_observations=settings.baseline_min_observations,
            )
            for m in BASELINE_METRICS
        }

        # Training-load EWMAs. Acute = 7d (alpha 2/8), chronic = 28d (alpha 2/29).
        hist = [series["training_load"].get(day - timedelta(days=i)) for i in range(0, 28)][::-1]
        acute = ewma(hist[-7:], 2 / 8)
        chronic = ewma(hist, 2 / 29)
        chronic_days = sum(1 for x in hist if x is not None)
        acwr = None
        if acute is not None and chronic is not None and chronic > 1e-6 and chronic_days >= 14:
            acwr = round(acute / chronic, 3)

        debt = sleep_debt(
            series["sleep_minutes"], day, settings.sleep_target_minutes, settings.sleep_debt_window_days
        )

        rec = compute_recovery(
            hrv=_num(vals.get("hrv_rmssd_ms")),
            resting_hr=_num(vals.get("resting_hr")),
            sleep_minutes=_num(vals.get("sleep_minutes")),
            sleep_efficiency=_num(vals.get("sleep_efficiency")),
            samsung_sleep_score=_num(vals.get("sleep_score")),
            training_load_yesterday=series["training_load"].get(day - timedelta(days=1)),
            acwr=acwr,
            baselines=baselines,
            checkin=checkins.get(day),
        )

        coverage = sum(
            1
            for i in range(14)
            if any(
                feats.get(day - timedelta(days=i), {}).get(k) is not None
                for k in ("sleep_minutes", "resting_hr", "steps", "hrv_rmssd_ms")
            )
        )
        conf = assess_confidence(
            baselines=baselines,
            missing_today=missing_map[day],
            effective_weights=rec.effective_weights,
            days_with_any_data_last_14=coverage,
        )

        explanation = {
            "model_version": "recovery-heuristic-v1",
            "recovery": rec.as_dict(),
            "confidence": {
                "level": conf.level,
                "reasons": conf.reasons,
                "baseline_days": conf.baseline_days,
                "coverage_14d": conf.coverage_14d,
                "weight_covered": conf.weight_covered,
            },
            "baselines": {
                m: {
                    "n": b.n,
                    "median": _round(b.median),
                    "mad": _round(b.mad),
                    "p25": _round(b.p25),
                    "p75": _round(b.p75),
                    "confidence": b.confidence,
                }
                for m, b in baselines.items()
                if b.usable
            },
            "deviations": {
                "hrv_pct": _round(baselines["hrv_rmssd_ms"].deviation_pct(_num(vals.get("hrv_rmssd_ms")))),
                "resting_hr_bpm": _round(
                    _sub(_num(vals.get("resting_hr")), baselines["resting_hr"].median)
                ),
                "sleep_minutes": _round(
                    _sub(_num(vals.get("sleep_minutes")), baselines["sleep_minutes"].median)
                ),
                "sleep_pct": _round(baselines["sleep_minutes"].deviation_pct(_num(vals.get("sleep_minutes")))),
                "steps_pct": _round(baselines["steps"].deviation_pct(_num(vals.get("steps")))),
            },
            "load": {
                "acute_7d": _round(acute),
                "chronic_28d": _round(chronic),
                "acwr": acwr,
                "chronic_observed_days": chronic_days,
            },
        }

        row = db.get(models.DailyFeature, day) or models.DailyFeature(day=day)
        row.sleep_minutes = _num(vals.get("sleep_minutes"))
        row.sleep_efficiency = _num(vals.get("sleep_efficiency"))
        row.deep_sleep_minutes = _num(vals.get("deep_sleep_minutes"))
        row.rem_sleep_minutes = _num(vals.get("rem_sleep_minutes"))
        row.light_sleep_minutes = _num(vals.get("light_sleep_minutes"))
        row.awake_minutes = _num(vals.get("awake_minutes"))
        row.sleep_score = _num(vals.get("sleep_score"))
        row.sleep_debt_minutes = debt
        row.bedtime_local_min = _num(vals.get("bedtime_local_min"))
        row.waketime_local_min = _num(vals.get("waketime_local_min"))
        row.sleep_midpoint_local_min = _num(vals.get("sleep_midpoint_local_min"))
        row.resting_hr = _num(vals.get("resting_hr"))
        row.avg_sleep_hr = _num(vals.get("avg_sleep_hr"))
        row.hrv_rmssd_ms = _num(vals.get("hrv_rmssd_ms"))
        row.steps = int(vals["steps"]) if vals.get("steps") is not None else None
        row.active_calories = _num(vals.get("active_calories"))
        row.workout_minutes = _num(vals.get("workout_minutes"))
        row.workout_count = int(vals["workout_count"]) if vals.get("workout_count") is not None else None
        row.training_load = _num(vals.get("training_load"))
        row.acute_load_7d = _round(acute)
        row.chronic_load_28d = _round(chronic)
        row.acwr = acwr
        row.weight_kg = _num(vals.get("weight_kg"))
        row.body_fat_pct = _num(vals.get("body_fat_pct"))
        row.hrv_zscore = _round(baselines["hrv_rmssd_ms"].robust_z(_num(vals.get("hrv_rmssd_ms"))))
        row.resting_hr_zscore = _round(baselines["resting_hr"].robust_z(_num(vals.get("resting_hr"))))
        row.sleep_zscore = _round(baselines["sleep_minutes"].robust_z(_num(vals.get("sleep_minutes"))))
        row.recovery_score = rec.recovery_score
        row.readiness_score = rec.readiness_score
        row.confidence = conf.level
        row.explanation = explanation
        row.missing_fields = {"today": missing_map[day]}
        db.add(row)
        written += 1

    db.flush()
    log.info("pipeline: rebuilt %d daily_features rows (%s..%s)", written, start, end)
    return written


def _num(x) -> float | None:  # type: ignore[no-untyped-def]
    if x is None or isinstance(x, str):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _round(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(x, nd)


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b
