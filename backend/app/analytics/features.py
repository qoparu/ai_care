"""Daily feature engine.

One row per LOCAL calendar day. Deterministic: same inputs -> same outputs,
no randomness, no clock reads inside the math. Missing stays missing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Relative-intensity fallbacks when no heart rate was recorded for a workout.
# These are coarse MET-like multipliers, only used to keep training load from
# being silently zero. Documented in docs/METRICS.md.
EXERCISE_INTENSITY_FALLBACK: dict[str, float] = {
    "running": 1.0,
    "treadmill": 0.9,
    "cycling": 0.85,
    "swimming": 0.95,
    "hiking": 0.7,
    "walking": 0.4,
    "strength": 0.65,
    "weight_machine": 0.6,
    "hiit": 1.1,
    "boxing": 1.0,
    "yoga": 0.35,
    "pilates": 0.4,
    "elliptical": 0.8,
    "rowing": 0.95,
    "dancing": 0.7,
    "other": 0.6,
}
DEFAULT_INTENSITY = 0.6


def local_date(ts: datetime, tz: str) -> Date:
    """Local calendar date of an aware timestamp."""
    if ts.tzinfo is None:
        raise ValueError("naive datetime passed to local_date")
    return ts.astimezone(ZoneInfo(tz)).date()


def minutes_since_midnight(ts: datetime, tz: str, *, unwrap_night: bool = False) -> float:
    """Local wall-clock position in minutes.

    With unwrap_night=True, times between 00:00 and 12:00 are shifted by +1440
    so that bedtimes of 23:40 and 00:20 are 40 minutes apart rather than 1400.
    """
    loc = ts.astimezone(ZoneInfo(tz))
    m = loc.hour * 60 + loc.minute + loc.second / 60.0
    if unwrap_night and m < 720:
        m += 1440
    return m


@dataclass
class DayInputs:
    """Everything the engine needs for one day, already fetched from the DB."""

    day: Date
    sleep: dict | None = None  # merged main sleep session for this day
    metrics: dict | None = None  # daily_metrics row
    workouts: list[dict] = field(default_factory=list)
    body: dict | None = None
    activity_synced: bool = False  # True if ANY activity data exists for the day


@dataclass
class DayFeatures:
    day: Date
    values: dict[str, float | int | None]
    missing: list[str]

    def get(self, key: str) -> float | None:
        v = self.values.get(key)
        return None if v is None else float(v)


def merge_sleep_sessions(sessions: list[dict]) -> dict | None:
    """Pick / combine sleep sessions attributed to one day.

    Samsung often reports the main night plus short naps. We take the LONGEST
    session as the main night and sum stage minutes across all sessions that
    overlap it; naps that do not overlap are ignored for the "main night"
    metrics (they still count in nothing else - documented, not silently mixed).
    """
    if not sessions:
        return None
    main = max(sessions, key=lambda s: (s.get("duration_min") or 0.0))
    return main


def trimp(
    duration_min: float,
    avg_hr: float | None,
    resting_hr: float | None,
    hr_max: int | None,
    sex: str,
) -> float | None:
    """Banister TRIMP with sex-specific weighting.

    TRIMP = duration * HRr * a * exp(b * HRr)
      HRr = (HRavg - HRrest) / (HRmax - HRrest)
      female: a=0.86, b=1.67   male: a=0.64, b=1.92
    Returns None when the required inputs are absent - we do not guess.
    """
    if avg_hr is None or resting_hr is None or hr_max is None:
        return None
    denom = hr_max - resting_hr
    if denom <= 0:
        return None
    hrr = (avg_hr - resting_hr) / denom
    hrr = max(0.0, min(1.0, hrr))
    a, b = (0.86, 1.67) if sex == "female" else (0.64, 1.92)
    return duration_min * hrr * a * math.exp(b * hrr)


def workout_load(
    w: dict, resting_hr: float | None, hr_max: int | None, sex: str
) -> tuple[float, str]:
    """Training load for one workout, plus the method used (for explainability)."""
    duration_min = (w.get("duration_sec") or 0) / 60.0
    if duration_min <= 0 and w.get("ended_at") and w.get("started_at"):
        duration_min = (w["ended_at"] - w["started_at"]).total_seconds() / 60.0
    duration_min = max(0.0, duration_min)
    if duration_min == 0:
        return 0.0, "zero_duration"

    t = trimp(duration_min, w.get("avg_hr"), resting_hr, hr_max, sex)
    if t is not None:
        return t, "trimp"

    key = (w.get("exercise_type") or "other").lower().replace(" ", "_")
    factor = EXERCISE_INTENSITY_FALLBACK.get(key, DEFAULT_INTENSITY)
    return duration_min * factor, f"duration_x_type_factor({key}={factor})"


def compute_day_features(
    inp: DayInputs,
    *,
    tz: str,
    sex: str,
    hr_max: int | None,
) -> DayFeatures:
    v: dict[str, float | int | None] = {}
    missing: list[str] = []

    def put(key: str, value, *, required: bool = True) -> None:  # type: ignore[no-untyped-def]
        v[key] = value
        if value is None and required:
            missing.append(key)

    s = inp.sleep
    if s:
        duration = s.get("duration_min")
        awake = s.get("awake_min")
        actual = s.get("actual_sleep_min")
        if actual is None and duration is not None and awake is not None:
            actual = max(0.0, duration - awake)
        eff = s.get("sleep_efficiency")
        if eff is None and actual is not None and duration and duration > 0:
            eff = actual / duration * 100.0

        put("sleep_minutes", actual if actual is not None else duration)
        put("sleep_efficiency", eff)
        put("deep_sleep_minutes", s.get("deep_min"), required=False)
        put("rem_sleep_minutes", s.get("rem_min"), required=False)
        put("light_sleep_minutes", s.get("light_min"), required=False)
        put("awake_minutes", awake, required=False)
        put("sleep_score", s.get("sleep_score"), required=False)
        put("avg_sleep_hr", s.get("avg_hr"), required=False)
        start, end = s.get("sleep_start"), s.get("sleep_end")
        put("bedtime_local_min", minutes_since_midnight(start, tz, unwrap_night=True) if start else None, required=False)
        put("waketime_local_min", minutes_since_midnight(end, tz) if end else None, required=False)
        if start and end:
            mid = start + (end - start) / 2
            put("sleep_midpoint_local_min", minutes_since_midnight(mid, tz, unwrap_night=True), required=False)
        else:
            put("sleep_midpoint_local_min", None, required=False)
    else:
        for k in (
            "sleep_minutes",
            "sleep_efficiency",
            "deep_sleep_minutes",
            "rem_sleep_minutes",
            "light_sleep_minutes",
            "awake_minutes",
            "sleep_score",
            "avg_sleep_hr",
            "bedtime_local_min",
            "waketime_local_min",
            "sleep_midpoint_local_min",
        ):
            v[k] = None
        missing.append("sleep_minutes")
        missing.append("sleep_efficiency")

    m = inp.metrics or {}
    put("resting_hr", m.get("resting_hr"))
    put("hrv_rmssd_ms", m.get("hrv_rmssd_ms"))
    put("steps", m.get("steps"), required=False)
    put("active_calories", m.get("active_kcal"), required=False)
    put("energy_score", m.get("energy_score"), required=False)
    if v.get("avg_sleep_hr") is None and m.get("sleeping_hr") is not None:
        v["avg_sleep_hr"] = m["sleeping_hr"]

    # --- training load ---------------------------------------------------
    resting = v.get("resting_hr")
    methods: list[str] = []
    total_load = 0.0
    workout_min = 0.0
    for w in inp.workouts:
        load, method = workout_load(w, resting, hr_max, sex)  # type: ignore[arg-type]
        total_load += load
        dur = (w.get("duration_sec") or 0) / 60.0
        workout_min += max(0.0, dur)
        methods.append(method)

    if inp.workouts:
        v["training_load"] = round(total_load, 2)
        v["workout_minutes"] = round(workout_min, 1)
        v["workout_count"] = len(inp.workouts)
    elif inp.activity_synced:
        # Data for the day exists and contains no workout: a real zero.
        v["training_load"] = 0.0
        v["workout_minutes"] = 0.0
        v["workout_count"] = 0
    else:
        # No data synced at all: unknown, NOT zero. (Engineering rule #2.)
        v["training_load"] = None
        v["workout_minutes"] = None
        v["workout_count"] = None
        missing.append("training_load")

    b = inp.body or {}
    v["weight_kg"] = b.get("weight_kg")
    v["body_fat_pct"] = b.get("body_fat_pct")

    return DayFeatures(day=inp.day, values=v, missing=sorted(set(missing)))


def sleep_debt(
    sleep_by_day: dict[Date, float | None],
    as_of: Date,
    target_min: float,
    window_days: int = 7,
) -> float | None:
    """Cumulative shortfall vs target over the trailing window (today included).

    Only observed nights count. Surplus sleep offsets debt but the total is
    floored at 0 - you cannot bank negative debt indefinitely.
    """
    total = 0.0
    observed = 0
    for i in range(window_days):
        d = as_of - timedelta(days=i)
        val = sleep_by_day.get(d)
        if val is None:
            continue
        observed += 1
        total += target_min - val
    if observed == 0:
        return None
    return max(0.0, round(total, 1))
