from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analytics.baseline import Baseline, compute_baseline, ewma

AS_OF = date(2026, 9, 3)


def series(values: list[float | None], end: date = AS_OF) -> dict[date, float | None]:
    """Map values onto the days ENDING the day before `end` (trailing window)."""
    return {end - timedelta(days=len(values) - i): v for i, v in enumerate(values)}


def test_too_few_observations_is_not_usable():
    bl = compute_baseline("hrv", series([50.0, 52.0]), AS_OF, min_observations=3)
    assert bl.n == 2
    assert not bl.usable
    assert bl.robust_z(40.0) is None
    assert bl.confidence == "LOW"


def test_median_and_mad_are_robust_to_one_outlier():
    clean = compute_baseline("hrv", series([50, 51, 52, 53, 54.0]), AS_OF)
    dirty = compute_baseline("hrv", series([50, 51, 52, 53, 400.0]), AS_OF)
    assert clean.median == dirty.median == 52.0
    # The mean is wrecked by the outlier; the median is not. That is the point.
    assert dirty.mean > 100 and clean.mean == pytest.approx(52.0)


def test_today_is_excluded_from_its_own_baseline():
    s = {AS_OF - timedelta(days=i): 50.0 for i in range(1, 11)}
    s[AS_OF] = 999.0
    bl = compute_baseline("hrv", s, AS_OF)
    assert bl.n == 10
    assert bl.median == 50.0
    assert 999.0 not in bl.values


def test_window_excludes_older_days():
    s = {AS_OF - timedelta(days=i): float(i) for i in range(1, 60)}
    bl = compute_baseline("hrv", s, AS_OF, window_days=28)
    assert bl.n == 28


def test_missing_days_are_dropped_not_imputed():
    bl = compute_baseline("hrv", series([50.0, None, 52.0, None, 54.0]), AS_OF)
    assert bl.n == 3
    assert bl.median == 52.0


def test_zero_mad_falls_back_so_z_stays_finite():
    """A perfectly flat series makes MAD 0 — z must not become inf or NaN."""
    bl = compute_baseline("rhr", series([58.0] * 10), AS_OF)
    assert bl.mad == 0.0
    z = bl.robust_z(61.0)
    assert z is not None and abs(z) < 5


def test_z_is_clamped():
    bl = compute_baseline("hrv", series([50, 52, 54, 56, 58.0]), AS_OF)
    assert bl.robust_z(100000.0) == 4.0
    assert bl.robust_z(-100000.0) == -4.0


def test_deviation_pct():
    bl = compute_baseline("hrv", series([50, 50, 50, 50.0]), AS_OF)
    assert bl.deviation_pct(40.0) == pytest.approx(-20.0)
    assert bl.deviation_pct(None) is None


def test_confidence_tiers():
    assert compute_baseline("x", series([1.0] * 5), AS_OF, window_days=90).confidence == "LOW"
    assert compute_baseline("x", series([1.0] * 20), AS_OF, window_days=90).confidence == "MEDIUM"
    assert compute_baseline("x", series([1.0] * 30), AS_OF, window_days=90).confidence == "HIGH"


def test_ewma_skips_missing_and_returns_none_when_empty():
    assert ewma([None, None], 0.3) is None
    assert ewma([10.0, None, 10.0], 0.5) == pytest.approx(10.0)
    assert ewma([0.0, 100.0], 0.5) == pytest.approx(50.0)


def test_unusable_baseline_returns_none_everywhere():
    bl = Baseline("x", 0, 28)
    assert bl.robust_z(5.0) is None
    assert bl.spread() is None
