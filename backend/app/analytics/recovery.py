"""Recovery and readiness scoring.

This is a TRANSPARENT HEURISTIC, not a validated physiological model. The
weights below are hypotheses. Everything is reported with its contribution so
any number can be traced back to the feature that produced it.

Mapping from robust z-score to a 0-100 component score:

    score = clip(NEUTRAL + SLOPE * z_directional, 0, 100)

`z_directional` flips sign for metrics where lower is better (resting HR).

CALIBRATION. NEUTRAL is the score of a day that sits exactly on your personal
baseline, and it is 72 - not 50. That is deliberate. The bands below come from
the project brief (82/65/45) and they describe a *training-readiness* scale,
where an ordinary average day should read "train as planned", not "back off".
Anchoring the neutral point at 50 made every statistically normal day land in
ORANGE, which is both wrong and useless. With NEUTRAL=72 and SLOPE=11:

    z = 0      -> 72   your normal day            (YELLOW, upper half)
    z = +0.91  -> 82   clearly better than normal (GREEN)
    z = -0.64  -> 65   noticeably below normal    (ORANGE boundary)
    z = -2.45  -> 45   far below normal           (RED boundary)

These numbers are a calibration choice, not a physiological finding. They are
in one place so they can be re-tuned once real personal data exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.analytics.baseline import Baseline

DEFAULT_WEIGHTS: dict[str, float] = {
    "hrv": 0.35,
    "resting_hr": 0.25,
    "sleep": 0.25,
    "load": 0.15,
}

BANDS: list[tuple[float, str, str]] = [
    (82.0, "GREEN", "🟢"),
    (65.0, "YELLOW", "🟡"),
    (45.0, "ORANGE", "🟠"),
    (0.0, "RED", "🔴"),
]

SLOPE = 11.0
NEUTRAL = 72.0

# A score is only emitted when this much of the model's intended weight was
# actually backed by data. Below it, the remaining components would be
# renormalized to 100% and produce a confident-looking verdict from a single
# signal - e.g. calling a day RED on training load alone, on a day the watch
# was not worn. Refusing to score is the correct answer there.
MIN_WEIGHT_COVERED = 0.40
# Sleeping far MORE than usual is weak evidence of good recovery, so upside is
# capped at +1.5 z while the downside runs the full range.
SLEEP_UPSIDE_Z_CAP = 1.5


def band_for(score: float | None) -> tuple[str | None, str | None]:
    if score is None:
        return None, None
    for threshold, name, emoji in BANDS:
        if score >= threshold:
            return name, emoji
    return "RED", "🔴"


def z_to_score(z: float | None, *, invert: bool = False, upside_cap: float | None = None) -> float | None:
    if z is None:
        return None
    zz = -z if invert else z
    if upside_cap is not None:
        zz = min(zz, upside_cap)
    return max(0.0, min(100.0, NEUTRAL + SLOPE * zz))


@dataclass
class Component:
    name: str
    score: float | None
    weight: float
    detail: str
    inputs: dict = field(default_factory=dict)


@dataclass
class RecoveryResult:
    recovery_score: float | None
    readiness_score: float | None
    band: str | None
    band_emoji: str | None
    components: list[Component]
    contributions: list[dict]
    effective_weights: dict[str, float]
    notes: list[str]

    def as_dict(self) -> dict:
        return {
            "recovery_score": self.recovery_score,
            "readiness_score": self.readiness_score,
            "band": self.band,
            "band_emoji": self.band_emoji,
            "effective_weights": self.effective_weights,
            "contributions": self.contributions,
            "components": [
                {"name": c.name, "score": c.score, "weight": c.weight, "detail": c.detail, "inputs": c.inputs}
                for c in self.components
            ],
            "notes": self.notes,
        }


def _load_component(
    training_load_yesterday: float | None,
    acwr: float | None,
    load_baseline: Baseline | None,
) -> Component:
    """Yesterday's stress on the system.

    Two independent signals:
      * how hard yesterday was relative to a typical day (robust z, inverted);
      * acute:chronic workload ratio, when there is enough history for it to
        mean anything (>=14 chronic days, enforced by the caller).
    """
    parts: list[float] = []
    detail_bits: list[str] = []

    if load_baseline is not None and load_baseline.usable and training_load_yesterday is not None:
        z = load_baseline.robust_z(training_load_yesterday)
        s = z_to_score(z, invert=True)
        if s is not None:
            parts.append(s)
            detail_bits.append(f"yesterday load z={z:+.2f} vs {load_baseline.n}d baseline")

    if acwr is not None:
        # Sweet spot 0.8-1.3. Below = detrained/undertrained (mild), above = spike.
        if 0.8 <= acwr <= 1.3:
            s = NEUTRAL + 4.0  # well-matched acute and chronic load
        elif acwr < 0.8:
            # Undertrained relative to your own chronic load: mildly negative.
            s = NEUTRAL - 6.0 * (0.8 - acwr) / 0.8
        else:
            # Acute spike: the further past 1.3, the harder the penalty.
            s = max(0.0, NEUTRAL + 4.0 - (acwr - 1.3) * 55.0)
        parts.append(s)
        detail_bits.append(f"ACWR={acwr:.2f}")

    if not parts:
        return Component("load", None, DEFAULT_WEIGHTS["load"], "no training-load history", {})
    score = sum(parts) / len(parts)
    return Component(
        "load",
        round(score, 1),
        DEFAULT_WEIGHTS["load"],
        "; ".join(detail_bits),
        {"training_load_yesterday": training_load_yesterday, "acwr": acwr},
    )


def _sleep_component(
    sleep_minutes: float | None,
    sleep_efficiency: float | None,
    samsung_sleep_score: float | None,
    sleep_baseline: Baseline,
    efficiency_baseline: Baseline,
) -> Component:
    parts: list[tuple[float, float]] = []  # (score, weight)
    bits: list[str] = []

    z_dur = sleep_baseline.robust_z(sleep_minutes)
    s_dur = z_to_score(z_dur, upside_cap=SLEEP_UPSIDE_Z_CAP)
    if s_dur is not None:
        parts.append((s_dur, 0.6))
        bits.append(f"duration z={z_dur:+.2f}")

    z_eff = efficiency_baseline.robust_z(sleep_efficiency)
    s_eff = z_to_score(z_eff, upside_cap=SLEEP_UPSIDE_Z_CAP)
    if s_eff is not None:
        parts.append((s_eff, 0.25))
        bits.append(f"efficiency z={z_eff:+.2f}")

    if samsung_sleep_score is not None:
        parts.append((float(samsung_sleep_score), 0.15))
        bits.append(f"Samsung sleep score={samsung_sleep_score:.0f}")

    if not parts:
        return Component("sleep", None, DEFAULT_WEIGHTS["sleep"], "no sleep baseline yet", {})

    wsum = sum(w for _, w in parts)
    score = sum(s * w for s, w in parts) / wsum
    return Component(
        "sleep",
        round(score, 1),
        DEFAULT_WEIGHTS["sleep"],
        "; ".join(bits),
        {
            "sleep_minutes": sleep_minutes,
            "sleep_efficiency": sleep_efficiency,
            "samsung_sleep_score": samsung_sleep_score,
        },
    )


def compute_recovery(
    *,
    hrv: float | None,
    resting_hr: float | None,
    sleep_minutes: float | None,
    sleep_efficiency: float | None,
    samsung_sleep_score: float | None,
    training_load_yesterday: float | None,
    acwr: float | None,
    baselines: dict[str, Baseline],
    checkin: dict | None = None,
) -> RecoveryResult:
    """Weighted, explainable recovery score.

    Components with no usable baseline are DROPPED and the remaining weights
    are renormalized - never imputed to a neutral 50, which would silently
    fabricate evidence.
    """
    notes: list[str] = []

    hrv_bl = baselines.get("hrv_rmssd_ms")
    rhr_bl = baselines.get("resting_hr")
    sleep_bl = baselines.get("sleep_minutes")
    eff_bl = baselines.get("sleep_efficiency")
    load_bl = baselines.get("training_load")

    z_hrv = hrv_bl.robust_z(hrv) if hrv_bl else None
    hrv_c = Component(
        "hrv",
        z_to_score(z_hrv),
        DEFAULT_WEIGHTS["hrv"],
        f"HRV {hrv:.0f} ms, z={z_hrv:+.2f} vs {hrv_bl.n}d baseline" if z_hrv is not None and hrv is not None and hrv_bl else "no HRV baseline yet",
        {"hrv": hrv, "z": z_hrv, "baseline_median": hrv_bl.median if hrv_bl else None},
    )

    z_rhr = rhr_bl.robust_z(resting_hr) if rhr_bl else None
    rhr_c = Component(
        "resting_hr",
        z_to_score(z_rhr, invert=True),
        DEFAULT_WEIGHTS["resting_hr"],
        f"resting HR {resting_hr:.0f} bpm, z={z_rhr:+.2f} vs {rhr_bl.n}d baseline" if z_rhr is not None and resting_hr is not None and rhr_bl else "no resting-HR baseline yet",
        {"resting_hr": resting_hr, "z": z_rhr, "baseline_median": rhr_bl.median if rhr_bl else None},
    )

    sleep_c = _sleep_component(
        sleep_minutes,
        sleep_efficiency,
        samsung_sleep_score,
        sleep_bl or Baseline("sleep_minutes", 0, 0),
        eff_bl or Baseline("sleep_efficiency", 0, 0),
    )
    load_c = _load_component(training_load_yesterday, acwr, load_bl)

    components = [hrv_c, rhr_c, sleep_c, load_c]
    available = [c for c in components if c.score is not None]
    if not available:
        return RecoveryResult(None, None, None, None, components, [], {}, ["no component had enough data"])

    wsum = sum(c.weight for c in available)
    if wsum < MIN_WEIGHT_COVERED:
        have = ", ".join(c.name for c in available)
        return RecoveryResult(
            None,
            None,
            None,
            None,
            components,
            [],
            {},
            [
                f"only {wsum:.0%} of model weight had data (need {MIN_WEIGHT_COVERED:.0%}); "
                f"scoring refused rather than extrapolating from: {have}"
            ],
        )

    effective = {c.name: round(c.weight / wsum, 4) for c in available}
    if len(available) < len(components):
        dropped = [c.name for c in components if c.score is None]
        notes.append(f"components dropped for lack of data: {', '.join(dropped)}; weights renormalized")

    recovery = sum(effective[c.name] * c.score for c in available)  # type: ignore[operator]
    recovery = round(max(0.0, min(100.0, recovery)), 1)

    contributions = sorted(
        [
            {
                "component": c.name,
                "weight": effective[c.name],
                "score": c.score,
                # Points this component pushed the score away from neutral 50.
                "contribution": round(effective[c.name] * (c.score - NEUTRAL), 1),  # type: ignore[operator]
                "detail": c.detail,
            }
            for c in available
        ],
        key=lambda d: d["contribution"],
    )

    # --- readiness: recovery adjusted by things recovery deliberately excludes
    readiness = recovery
    if checkin:
        subj = [checkin.get("energy"), checkin.get("mood")]
        subj = [x for x in subj if x is not None]
        sore = checkin.get("soreness")
        adj = 0.0
        if subj:
            mean_subj = sum(subj) / len(subj)  # 1..5, 3 = neutral
            adj += (mean_subj - 3.0) * 5.0  # +/- 10 points max
            notes.append(f"subjective energy/mood {mean_subj:.1f}/5 -> {(mean_subj - 3.0) * 5.0:+.1f}")
        if sore is not None:
            adj += (3.0 - sore) * 2.5  # soreness 5 -> -5
            notes.append(f"soreness {sore}/5 -> {(3.0 - sore) * 2.5:+.1f}")
        readiness = max(0.0, min(100.0, recovery + adj))
    else:
        notes.append("no check-in for this day; readiness = recovery")

    if acwr is not None and acwr > 1.5:
        readiness = max(0.0, readiness - 5.0)
        notes.append(f"ACWR {acwr:.2f} > 1.5 -> readiness -5 (acute load spike)")

    name, emoji = band_for(recovery)
    return RecoveryResult(
        recovery_score=recovery,
        readiness_score=round(readiness, 1),
        band=name,
        band_emoji=emoji,
        components=components,
        contributions=contributions,
        effective_weights=effective,
        notes=notes,
    )
