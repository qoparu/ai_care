# Metric definitions

Engineering rule #6: every derived metric has a documented definition. This is
that document. If code and this file disagree, the code is the bug.

All formulas live in `backend/app/analytics/` and are covered by tests in
`backend/tests/`.

---

## Day attribution and timezones

Every timestamp crossing the API must be timezone-aware (RFC3339 with offset).
Naive timestamps are rejected, not assumed.

| Record | Assigned to |
|---|---|
| Sleep session | local calendar date of **wake-up** (`sleep_end`) |
| Daily metric | the `date` field as reported by Samsung Health |
| Workout | local calendar date of **start** |
| Body measurement | local calendar date of measurement |

"Local" means `TIMEZONE` from settings (default `Asia/Almaty`). A session
starting 23:40 on the 2nd and ending 07:15 on the 3rd belongs to the 3rd.

Bedtime and sleep-midpoint are stored as minutes since local midnight with
**night unwrapping**: values before 12:00 get +1440, so 23:40 and 00:20 are 40
minutes apart rather than 1400. Without this, sleep-consistency statistics are
nonsense.

---

## Sleep

| Metric | Definition |
|---|---|
| `sleep_minutes` | `actual_sleep_min` if reported, else `duration_min - awake_min`, else `duration_min` |
| `sleep_efficiency` | reported value, else `actual_sleep / time_in_bed * 100` |
| `deep/rem/light/awake_minutes` | passed through from the source, never derived |
| `sleep_score` | Samsung's own score, passed through. Not recomputed. |
| `sleep_debt_minutes` | `max(0, Σ over last 7 measured nights (target - actual))`, target = `SLEEP_TARGET_MINUTES` (480). Unmeasured nights are skipped, not counted as zero debt or full debt. |
| `bedtime_local_min` / `waketime_local_min` / `sleep_midpoint_local_min` | see night unwrapping above |

---

## Cardiovascular

Passed through from Samsung Health; the backend does not derive resting HR from
raw samples (the watch has far better context for that than we do).

| Metric | Definition |
|---|---|
| `resting_hr` | reported daily resting heart rate, bpm |
| `avg_sleep_hr` | sleep-session average HR, falling back to the daily `sleeping_hr` |
| `hrv_rmssd_ms` | RMSSD in milliseconds as reported. **Not** interchangeable with SDNN. |

If Samsung reports HRV under a different definition than RMSSD, map it in the
collector — do not silently write it into `hrv_rmssd_ms`.

---

## Training load

### TRIMP (preferred)

Banister's training impulse, with sex-specific weighting:

```
HRr   = (HR_avg - HR_rest) / (HR_max - HR_rest)      clamped to [0, 1]
TRIMP = duration_min * HRr * a * exp(b * HRr)
        female: a = 0.86, b = 1.67
        male:   a = 0.64, b = 1.92
```

`HR_max` comes from `HR_MAX_OVERRIDE` if set, otherwise Tanaka et al. (2001):
`208 - 0.7 * age`. That regression has roughly ±10 bpm individual error, so
TRIMP here is a **relative** load index for comparing your own days — not a
number to compare against anyone else.

### Fallback

When HR data is missing, load falls back to `duration_min * type_factor`, with
factors listed in `EXERCISE_INTENSITY_FALLBACK` (`features.py`). The method
used is recorded per workout so the number is never anonymous.

### Daily load and ratios

| Metric | Definition |
|---|---|
| `training_load` | Σ TRIMP over that day's workouts. **0 only when activity data exists and contains no workout.** No data at all → `NULL`. |
| `acute_load_7d` | EWMA of daily load, α = 2/8 |
| `chronic_load_28d` | EWMA of daily load, α = 2/29 |
| `acwr` | `acute / chronic`, emitted **only** when at least 14 chronic days were observed. Below that the ratio is noise. |

ACWR is contested in the sports-science literature. It is used here as one
input among several, never as a standalone verdict.

---

## Baseline

`backend/app/analytics/baseline.py`.

- Trailing window of `BASELINE_WINDOW_DAYS` (28), **excluding the day being
  scored** — otherwise a day is compared to a baseline containing itself.
- Robust statistics: median, and MAD scaled by 1.4826.
- Missing days are dropped, never imputed.
- Minimum 3 observations, else the baseline is unusable and no z-score is produced.

**Robust z-score:**

```
z = (value - median) / scale        clamped to [-4, +4]
scale = max(MAD, std, 0.05 * |median|)
```

The scale floor matters: a perfectly flat series (identical resting HR every
day) makes MAD exactly 0 and would send z to infinity.

**Baseline confidence:** `n ≥ 28` HIGH, `n ≥ 14` MEDIUM, else LOW.

---

## Recovery score

`backend/app/analytics/recovery.py`. A transparent heuristic. **The weights are
hypotheses, not physiology.**

Component score from a robust z:

```
score = clip(NEUTRAL + SLOPE * z_directional, 0, 100)
NEUTRAL = 72     SLOPE = 11
```

`z_directional` is negated for metrics where lower is better (resting HR).

### Why NEUTRAL is 72 and not 50

The bands below (82 / 65 / 45) describe *training readiness*. With neutral at
50, a statistically ordinary day scored ~56 and landed in ORANGE — telling you
to skip training on a completely normal day. Anchored at 72:

| z | score | meaning |
|---|---|---|
| 0 | 72 | your normal day (YELLOW, upper half) |
| +0.91 | 82 | clearly better than normal (GREEN) |
| −0.64 | 65 | noticeably below normal (ORANGE boundary) |
| −2.45 | 45 | far below normal (RED boundary) |

This is a calibration choice. Re-tune it once real data exists.

### Weights

| Component | Weight | Built from |
|---|---|---|
| `hrv` | 0.35 | robust z of RMSSD |
| `resting_hr` | 0.25 | robust z of resting HR, inverted |
| `sleep` | 0.25 | 0.60 duration z + 0.25 efficiency z + 0.15 Samsung sleep score |
| `load` | 0.15 | yesterday's load z (inverted) and ACWR |

Sleep upside is capped at z = +1.5: sleeping far more than usual is weak
evidence of good recovery, while sleeping far less is strong evidence of bad.

### Missing components

Components without a usable baseline are **dropped** and the remaining weights
renormalized. They are never imputed to a neutral value, which would fabricate
evidence.

**Minimum coverage:** if the surviving components carry less than **40%** of the
model's intended weight, no score is emitted at all. This exists because a day
where the watch was not worn once produced a confident "RED — skip training"
from the training-load component alone.

### Bands

```
82–100  GREEN    train as planned
65–81   YELLOW   normal; trim volume on hard sessions
45–64   ORANGE   moderate work only
 0–44   RED      light movement, prioritise sleep
```

### Explainability

Every component reports `contribution = weight * (score - NEUTRAL)` — the points
it pushed the total away from your normal. Contributions sum to
`recovery_score - NEUTRAL`. A score with no explanation is a bug.

---

## Readiness score

Recovery, adjusted by information recovery deliberately excludes:

```
readiness = recovery
          + (mean(energy, mood) - 3) * 5      subjective check-in, ±10
          + (3 - soreness) * 2.5              ±5
          - 5 if ACWR > 1.5
```

Clamped to [0, 100]. With no check-in, readiness equals recovery.

---

## Confidence

`backend/app/analytics/confidence.py`. Starts from baseline size:

```
n ≥ 28 → HIGH,  n ≥ 14 → MEDIUM,  else LOW
```

then demotes one level for each of:

- a critical metric (HRV, resting HR, sleep) missing today;
- less than 75% of model weight backed by data;
- fewer than 10 of the last 14 days carrying any data.

Every demotion appends a human-readable reason. Confidence never reflects
whether the number looks good — only how much evidence stands behind it.
