"""Confidence in a day's result.

Confidence answers "how much should this number be trusted", and is driven by
evidence, not by how good the number looks. Four inputs:
  1. baseline size  - how many days the personal normal rests on
  2. missingness    - which components could not be computed today
  3. coverage       - how many of the last 14 days have data at all
  4. weight covered - how much of the model's weight actually had data
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.baseline import Baseline

CRITICAL = ("hrv_rmssd_ms", "resting_hr", "sleep_minutes")


@dataclass
class ConfidenceResult:
    level: str
    reasons: list[str]
    baseline_days: int
    coverage_14d: float
    weight_covered: float


def assess_confidence(
    *,
    baselines: dict[str, Baseline],
    missing_today: list[str],
    effective_weights: dict[str, float],
    days_with_any_data_last_14: int,
) -> ConfidenceResult:
    reasons: list[str] = []

    sizes = [baselines[m].n for m in CRITICAL if m in baselines]
    baseline_days = min(sizes) if sizes else 0

    coverage = days_with_any_data_last_14 / 14.0
    # How much of the model's intended weight was actually backed by data.
    from app.analytics.recovery import DEFAULT_WEIGHTS

    weight_covered = sum(DEFAULT_WEIGHTS[k] for k in effective_weights) if effective_weights else 0.0

    if baseline_days < 7:
        level = "LOW"
        reasons.append(f"personal baseline is only {baseline_days} day(s)")
    elif baseline_days < 14:
        level = "LOW"
        reasons.append(f"personal baseline is {baseline_days} days - preliminary, treat trends as provisional")
    elif baseline_days < 28:
        level = "MEDIUM"
        reasons.append(f"personal baseline is {baseline_days} days")
    else:
        level = "HIGH"
        reasons.append(f"personal baseline is {baseline_days} days")

    missing_critical = [m for m in CRITICAL if m in missing_today]
    if missing_critical:
        reasons.append(f"critical metrics missing today: {', '.join(missing_critical)}")
        level = _demote(level)

    if weight_covered < 0.75:
        reasons.append(f"only {weight_covered:.0%} of model weight had data")
        level = _demote(level)

    if coverage < 0.7:
        reasons.append(f"only {days_with_any_data_last_14}/14 recent days have any data")
        level = _demote(level)

    return ConfidenceResult(
        level=level,
        reasons=reasons,
        baseline_days=baseline_days,
        coverage_14d=round(coverage, 2),
        weight_covered=round(weight_covered, 2),
    )


def _demote(level: str) -> str:
    return {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}[level]
