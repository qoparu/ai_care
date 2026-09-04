from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.analytics.features import (
    DayInputs,
    compute_day_features,
    local_date,
    minutes_since_midnight,
    sleep_debt,
    trimp,
    workout_load,
)

TZ = "Asia/Almaty"  # UTC+5
ALM = ZoneInfo(TZ)

KW = dict(tz=TZ, sex="female", hr_max=194)


def test_local_date_uses_local_timezone_not_utc():
    # 21:30 UTC on the 2nd is 02:30 local on the 3rd.
    ts = datetime(2026, 9, 2, 21, 30, tzinfo=ZoneInfo("UTC"))
    assert local_date(ts, TZ) == date(2026, 9, 3)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="naive"):
        local_date(datetime(2026, 9, 3, 12, 0), TZ)


def test_bedtime_unwrapping_keeps_late_and_past_midnight_comparable():
    late = minutes_since_midnight(datetime(2026, 9, 2, 23, 40, tzinfo=ALM), TZ, unwrap_night=True)
    past = minutes_since_midnight(datetime(2026, 9, 3, 0, 20, tzinfo=ALM), TZ, unwrap_night=True)
    assert past - late == pytest.approx(40.0)


def test_trimp_returns_none_without_required_inputs():
    assert trimp(60, None, 55, 194, "female") is None
    assert trimp(60, 150, None, 194, "female") is None
    assert trimp(60, 150, 55, None, "female") is None


def test_trimp_increases_with_intensity_and_duration():
    easy = trimp(60, 120, 55, 194, "female")
    hard = trimp(60, 170, 55, 194, "female")
    longer = trimp(90, 120, 55, 194, "female")
    assert hard > easy and longer > easy


def test_workout_load_falls_back_to_type_factor_without_hr():
    load, method = workout_load({"duration_sec": 3600, "exercise_type": "yoga"}, None, None, "female")
    assert load == pytest.approx(60 * 0.35)
    assert "type_factor" in method


def test_no_workout_but_data_present_is_a_real_zero():
    f = compute_day_features(
        DayInputs(day=date(2026, 9, 3), metrics={"steps": 8000}, activity_synced=True), **KW
    )
    assert f.values["training_load"] == 0.0
    assert "training_load" not in f.missing


def test_no_data_at_all_is_missing_not_zero():
    """Engineering rule #2: never silently replace missing values with zero."""
    f = compute_day_features(DayInputs(day=date(2026, 9, 3)), **KW)
    assert f.values["training_load"] is None
    assert "training_load" in f.missing
    assert f.values["sleep_minutes"] is None
    assert "sleep_minutes" in f.missing


def test_sleep_efficiency_derived_when_not_reported():
    start = datetime(2026, 9, 2, 23, 0, tzinfo=ALM)
    end = start + timedelta(minutes=480)
    f = compute_day_features(
        DayInputs(
            day=date(2026, 9, 3),
            sleep={
                "sleep_start": start,
                "sleep_end": end,
                "duration_min": 480.0,
                "awake_min": 48.0,
                "actual_sleep_min": None,
                "sleep_efficiency": None,
            },
        ),
        **KW,
    )
    assert f.values["sleep_minutes"] == pytest.approx(432.0)
    assert f.values["sleep_efficiency"] == pytest.approx(90.0)


def test_sleep_debt_only_counts_observed_nights():
    days = {date(2026, 9, 3) - timedelta(days=i): 420.0 for i in range(7)}
    assert sleep_debt(days, date(2026, 9, 3), 480.0) == pytest.approx(420.0)
    assert sleep_debt({}, date(2026, 9, 3), 480.0) is None
    # Surplus cannot produce negative debt.
    good = {date(2026, 9, 3) - timedelta(days=i): 600.0 for i in range(7)}
    assert sleep_debt(good, date(2026, 9, 3), 480.0) == 0.0
