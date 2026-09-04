# Data model

Three layers. Each one can be rebuilt from the one above it.

```
raw_health_records     verbatim source payloads, never rewritten by analytics
        │
        ▼
sleep_sessions / daily_metrics / workouts / body_measurements / heart_rate_samples
        │              typed, validated, deduplicated by source_uid
        ▼
daily_features         one row per local day, deterministic derivation
```

`daily_features` is disposable. Delete it and run `POST /api/v1/recompute`;
you get byte-identical rows back (there is a test for exactly that).

## Deviations from the project brief's schema

The brief called this a starting point, not sacred. Three changes:

1. **`daily_metrics` replaces several single-purpose daily tables.** Resting HR,
   HRV, steps, calories and energy score are all one row per day from one
   source. Five tables joined on `date` bought nothing.
2. **`day` columns added** to `sleep_sessions`, `workouts` and
   `body_measurements`. Attribution rules (see METRICS.md) are non-trivial and
   belong in the write path, computed once, not re-derived in every query.
3. **`checkins` table added** for subjective data — section 10 of the brief
   describes it but the schema had nowhere to put it.

## Idempotency

Every normalized record carries a `source_uid`. The collector may re-send an
overlapping window as often as it likes: re-ingesting the same payload changes
no row counts and no scores.

`daily_metrics` merges rather than overwrites — a partial update never wipes a
previously known value with `NULL`.

## The synthetic flag

Every table has `is_synthetic`. Generated data is labelled at the row level, and
the API rejects synthetic payloads outright when `DATA_PROFILE=prod`. Test data
and real data never mix by accident.
