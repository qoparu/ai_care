"""Personal baseline computation.

Design rules:
  * Robust first. Median + MAD, not mean + std, because a single 3-hour night
    or a broken HRV reading should not redefine "normal".
  * Never fabricate. Missing days are excluded, not imputed with zero or mean.
  * The window is trailing and EXCLUDES the day being evaluated, otherwise a
    day is compared against a baseline that already contains it.
  * Sample size is reported, not hidden. A 5-day baseline is labelled a
    5-day baseline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta

MAD_TO_SIGMA = 1.4826  # makes MAD a consistent estimator of sigma for normal data
Z_CLAMP = 4.0


@dataclass(frozen=True)
class Baseline:
    metric: str
    n: int
    window_days: int
    median: float | None = None
    mad: float | None = None
    mean: float | None = None
    std: float | None = None
    p25: float | None = None
    p75: float | None = None
    values: tuple[float, ...] = field(default=(), repr=False)

    @property
    def confidence(self) -> str:
        """Confidence in the BASELINE itself (not in any downstream score)."""
        if self.n >= 28:
            return "HIGH"
        if self.n >= 14:
            return "MEDIUM"
        return "LOW"

    @property
    def usable(self) -> bool:
        return self.n >= 3 and self.median is not None

    def spread(self) -> float | None:
        """Best available scale estimate, with a floor so z-scores stay finite.

        MAD is preferred. It collapses to 0 when >50% of observations are
        identical (common with integer step goals or a flat resting HR), so we
        fall back to std, then to a 5% relative floor.
        """
        if self.median is None:
            return None
        candidates = [c for c in (self.mad, self.std) if c is not None and c > 1e-9]
        scale = max(candidates) if candidates else None
        floor = abs(self.median) * 0.05
        if scale is None or scale < floor:
            scale = floor
        return scale if scale > 1e-9 else None

    def robust_z(self, value: float | None) -> float | None:
        """Robust z-score: (x - median) / scale, clamped to +/-4."""
        if value is None or not self.usable:
            return None
        scale = self.spread()
        if scale is None:
            return None
        z = (value - self.median) / scale  # type: ignore[operator]
        return max(-Z_CLAMP, min(Z_CLAMP, z))

    def deviation_pct(self, value: float | None) -> float | None:
        if value is None or self.median is None or abs(self.median) < 1e-9:
            return None
        return (value - self.median) / self.median * 100.0


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _percentile(xs: list[float], p: float) -> float:
    """Linear-interpolation percentile (numpy 'linear' method), p in [0, 100]."""
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def compute_baseline(
    metric: str,
    series: dict[Date, float | None],
    as_of: Date,
    window_days: int = 28,
    min_observations: int = 3,
    exclude_today: bool = True,
) -> Baseline:
    """Trailing-window robust baseline for one metric.

    `series` maps day -> value (None = not measured). Days without a value are
    dropped, never imputed.
    """
    start = as_of - timedelta(days=window_days)
    end = as_of - timedelta(days=1) if exclude_today else as_of
    values = [
        v
        for d, v in series.items()
        if v is not None and start <= d <= end and math.isfinite(v)
    ]
    n = len(values)
    if n < min_observations:
        return Baseline(metric=metric, n=n, window_days=window_days, values=tuple(values))

    med = _median(values)
    mad = _median([abs(v - med) for v in values]) * MAD_TO_SIGMA
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    return Baseline(
        metric=metric,
        n=n,
        window_days=window_days,
        median=med,
        mad=mad,
        mean=mean,
        std=math.sqrt(var),
        p25=_percentile(values, 25),
        p75=_percentile(values, 75),
        values=tuple(values),
    )


def ewma(series: list[float | None], alpha: float) -> float | None:
    """Exponentially weighted moving average over an ordered series.

    None values are skipped (they carry no information), so the average is over
    observed days only. Returns None if nothing was observed.
    """
    acc: float | None = None
    for v in series:
        if v is None:
            continue
        acc = v if acc is None else alpha * v + (1 - alpha) * acc
    return acc
