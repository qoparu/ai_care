# Roadmap

## MVP v0.1 — definition of done

From the project brief, honestly marked:

- [x] raw records are preserved
- [x] normalized data is stored
- [x] PostgreSQL works (and SQLite for local dev/tests)
- [x] daily features are calculated
- [x] preliminary baseline is calculated
- [x] recovery score is deterministic
- [x] confidence is calculated
- [x] one LLM provider can interpret structured results (four can)
- [x] `/today` returns a useful report
- [x] no secret is committed
- [x] missing data does not crash the pipeline
- [ ] **Android app connects to Samsung Health**
- [ ] **permissions work**
- [ ] **at least 7 days of real data can be read**

The three open items are one task: the collector. Everything downstream is
finished and tested against synthetic data.

---

## Next, in order. Do not skip ahead.

### 1. The collector (blocking everything else)

Decide the route first:

- **Health Connect** — no Samsung approval, smaller data surface, simpler API.
  Fastest path to real data.
- **Samsung Health Data SDK + developer mode** — full surface including
  Samsung-specific metrics, more setup.

Recommendation: start with Health Connect. Getting 7 real days into the pipeline
this week beats a perfect SDK integration next month. The ingestion contract is
identical either way, so switching later costs nothing downstream.

Phase 0 checks before writing app code — the brief is right that none of these
should be assumed:

- which data types the Galaxy Watch 7 actually exposes;
- historical depth available (7 days? 30? more?);
- whether HRV is exposed at all, and under which definition (RMSSD vs SDNN);
- whether Energy Score is readable;
- timestamp and timezone semantics of each type.

Write the answers into `docs/INGESTION_CONTRACT.md` as you find them.

### 2. Fourteen real days

Do nothing else until this exists. Every weight in `recovery.py` is currently a
guess, and guesses cannot be improved without data.

### 3. Recalibrate

With real data in hand:

- Check the score distribution. If most days are not YELLOW, `NEUTRAL` or
  `SLOPE` in `recovery.py` is wrong.
- Check whether HRV deserves 0.35 of the weight, or whether resting HR is the
  more stable signal for you personally.
- Compare check-in energy against the recovery score. If they disagree
  systematically, the model is wrong, not you.

### 4. Longitudinal analysis (60–90 days minimum)

Only after enough observations exist:

- lagged correlations: `sleep(t-1) → HRV(t)`, `load(t-1) → sleep(t)`,
  `load(t-2) → HRV(t)`;
- simple linear models before anything else;
- regularized regression, then gradient boosting, only if linear fails and
  there are enough observations to justify it.

With ~90 days you have ~90 rows. That is a small dataset. Resist XGBoost.

---

## Deliberately not built yet

Not oversights — they need a reason to exist first:

- **Web dashboard.** Telegram covers the daily loop. Build it when you want to
  look at 90-day charts, not before.
- **Redis / Celery / Airflow.** There is one job and it takes milliseconds.
- **Multi-user support.** This is a single-user system by design; auth is one
  shared token.
- **Heart-rate zone analysis.** Needs a measured HRmax, not a regression estimate.
- **Nutrition, hydration, cycle tracking.** The brief says not until ingestion
  works. It is still not working.

---

## Known limitations

State these before anyone reads a number as truth:

1. **Weights are hypotheses.** 0.35 / 0.25 / 0.25 / 0.15 came from the brief, not
   from evidence.
2. **HRmax is a population regression** (Tanaka), ±10 bpm individual error. TRIMP
   here is relative to yourself only.
3. **ACWR is contested** in the literature. It is one input, not a verdict.
4. **A 28-day baseline is not a stable baseline.** It adapts to slow drift,
   which also means a bad month becomes the new normal.
5. **Consumer wearable HRV is noisy**, especially night-to-night. Trends over
   days mean more than any single value.
6. **Correlation is not causation**, and with ~90 daily observations most
   apparent relationships will not survive multiple-comparison correction.
