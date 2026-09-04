from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analytics.baseline import compute_baseline
from app.analytics.recovery import DEFAULT_WEIGHTS, band_for, compute_recovery

AS_OF = date(2026, 9, 3)


def bl(metric: str, value: float, n: int = 30, spread: float = 4.0):
    s = {AS_OF - timedelta(days=i + 1): value + (i % 3 - 1) * spread for i in range(n)}
    return compute_baseline(metric, s, AS_OF, window_days=90)


def full_baselines():
    return {
        "hrv_rmssd_ms": bl("hrv_rmssd_ms", 58.0),
        "resting_hr": bl("resting_hr", 57.0, spread=2.0),
        "sleep_minutes": bl("sleep_minutes", 450.0, spread=30.0),
        "sleep_efficiency": bl("sleep_efficiency", 91.0, spread=2.0),
        "training_load": bl("training_load", 60.0, spread=20.0),
    }


BASE_KW = dict(
    hrv=58.0,
    resting_hr=57.0,
    sleep_minutes=450.0,
    sleep_efficiency=91.0,
    samsung_sleep_score=None,
    training_load_yesterday=60.0,
    acwr=1.0,
)


def test_at_baseline_the_score_sits_near_neutral():
    r = compute_recovery(**BASE_KW, baselines=full_baselines())
    # An exactly-average day must read as "normal", not as a warning.
    assert 65 <= r.recovery_score <= 82


def test_deterministic():
    a = compute_recovery(**BASE_KW, baselines=full_baselines())
    b = compute_recovery(**BASE_KW, baselines=full_baselines())
    assert a.recovery_score == b.recovery_score
    assert a.contributions == b.contributions


def test_worse_inputs_lower_the_score_monotonically():
    good = compute_recovery(**{**BASE_KW, "hrv": 70.0}, baselines=full_baselines()).recovery_score
    mid = compute_recovery(**BASE_KW, baselines=full_baselines()).recovery_score
    bad = compute_recovery(**{**BASE_KW, "hrv": 40.0}, baselines=full_baselines()).recovery_score
    assert good > mid > bad


def test_missing_component_is_dropped_and_weights_renormalize():
    r = compute_recovery(**{**BASE_KW, "hrv": None}, baselines=full_baselines())
    assert "hrv" not in r.effective_weights
    assert sum(r.effective_weights.values()) == pytest.approx(1.0)
    assert any("dropped" in n for n in r.notes)


def test_missing_component_is_never_imputed_to_neutral():
    """A dropped component must not silently act as a neutral vote."""
    with_hrv_bad = compute_recovery(**{**BASE_KW, "hrv": 30.0}, baselines=full_baselines())
    without_hrv = compute_recovery(**{**BASE_KW, "hrv": None}, baselines=full_baselines())
    assert without_hrv.recovery_score > with_hrv_bad.recovery_score
    assert with_hrv_bad.effective_weights["hrv"] == pytest.approx(DEFAULT_WEIGHTS["hrv"])


def test_no_data_at_all_yields_no_score_rather_than_a_guess():
    r = compute_recovery(
        hrv=None,
        resting_hr=None,
        sleep_minutes=None,
        sleep_efficiency=None,
        samsung_sleep_score=None,
        training_load_yesterday=None,
        acwr=None,
        baselines={},
    )
    assert r.recovery_score is None and r.band is None


def test_contributions_sum_to_score_minus_neutral():
    r = compute_recovery(**BASE_KW, baselines=full_baselines())
    total = sum(c["contribution"] for c in r.contributions)
    from app.analytics.recovery import NEUTRAL

    assert total == pytest.approx(r.recovery_score - NEUTRAL, abs=0.35)


def test_every_contribution_carries_an_explanation():
    r = compute_recovery(**BASE_KW, baselines=full_baselines())
    assert r.contributions
    for c in r.contributions:
        assert c["detail"]
        assert set(c) == {"component", "weight", "score", "contribution", "detail"}


def test_bands():
    assert band_for(90)[0] == "GREEN"
    assert band_for(70)[0] == "YELLOW"
    assert band_for(50)[0] == "ORANGE"
    assert band_for(20)[0] == "RED"
    assert band_for(None) == (None, None)


def test_checkin_moves_readiness_but_not_recovery():
    base = compute_recovery(**BASE_KW, baselines=full_baselines())
    low = compute_recovery(
        **BASE_KW, baselines=full_baselines(), checkin={"energy": 1, "mood": 1, "soreness": 5}
    )
    assert low.recovery_score == base.recovery_score
    assert low.readiness_score < base.readiness_score


def test_acwr_spike_penalises_readiness():
    calm = compute_recovery(**BASE_KW, baselines=full_baselines())
    spike = compute_recovery(**{**BASE_KW, "acwr": 1.9}, baselines=full_baselines())
    assert spike.readiness_score < calm.readiness_score


def test_a_normal_day_is_not_flagged_as_a_warning():
    """Calibration guard.

    A day sitting exactly on the personal baseline must not read as ORANGE/RED.
    An earlier version anchored neutral at 50, which made every statistically
    ordinary day look like a reason to skip training.
    """
    r = compute_recovery(**BASE_KW, baselines=full_baselines())
    assert r.band in {"GREEN", "YELLOW"}
    assert all(c["contribution"] > -2.0 for c in r.contributions)


def test_a_clearly_bad_day_still_reaches_orange_or_red():
    bad = compute_recovery(
        **{
            **BASE_KW,
            "hrv": 40.0,
            "resting_hr": 65.0,
            "sleep_minutes": 300.0,
            "sleep_efficiency": 82.0,
        },
        baselines=full_baselines(),
    )
    assert bad.band in {"ORANGE", "RED"}


def test_scoring_is_refused_when_too_little_weight_has_data():
    """A single surviving component must not produce a confident verdict.

    Regression guard: a day where the watch was not worn once produced
    "RED - skip hard training" from the training-load component alone.
    """
    r = compute_recovery(
        hrv=None,
        resting_hr=None,
        sleep_minutes=None,
        sleep_efficiency=None,
        samsung_sleep_score=None,
        training_load_yesterday=140.0,
        acwr=1.9,
        baselines=full_baselines(),
    )
    assert r.recovery_score is None
    assert r.band is None
    assert any("scoring refused" in n for n in r.notes)


def test_two_solid_components_are_enough_to_score():
    r = compute_recovery(
        **{**BASE_KW, "hrv": None, "training_load_yesterday": None, "acwr": None},
        baselines=full_baselines(),
    )
    assert r.recovery_score is not None
    assert set(r.effective_weights) == {"resting_hr", "sleep"}
