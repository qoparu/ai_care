# Ingestion contract

`POST /api/v1/ingest` with `Authorization: Bearer <API_TOKEN>`.

This is the boundary between the Android collector and everything else. The
collector can be rewritten, replaced with a Health Connect reader, or swapped
for a laptop script — as long as it produces this shape.

The authoritative definition is `backend/app/schemas.py`; the live schema is at
`GET /docs`. Unknown fields are **rejected**, not ignored, so a typo fails loudly.

```json
{
  "collector_version": "android-collector/0.1.0",
  "device_id": "SM-R950",
  "source_package": "com.sec.android.app.shealth",
  "timezone": "Asia/Almaty",
  "is_synthetic": false,

  "sleep_sessions": [
    {
      "source_uid": "shealth-sleep-8f21ac",
      "start": "2026-09-02T23:41:00+05:00",
      "end":   "2026-09-03T07:26:00+05:00",
      "duration_min": 465,
      "actual_sleep_min": 432,
      "awake_min": 33,
      "deep_min": 72,
      "rem_min": 101,
      "light_min": 259,
      "sleep_efficiency": 92.9,
      "sleep_score": 74,
      "avg_hr": 58.4,
      "device_id": "SM-R950"
    }
  ],

  "daily_metrics": [
    {
      "date": "2026-09-03",
      "resting_hr": 61,
      "avg_hr": 78,
      "min_hr": 52,
      "max_hr": 154,
      "sleeping_hr": 59,
      "hrv_rmssd_ms": 47.2,
      "steps": 9234,
      "active_kcal": 487,
      "total_kcal": 1980,
      "distance_m": 7120,
      "energy_score": 68
    }
  ],

  "workouts": [
    {
      "source_uid": "shealth-ex-1a2b3c",
      "started_at": "2026-09-03T19:05:00+05:00",
      "ended_at":   "2026-09-03T20:05:00+05:00",
      "exercise_type": "boxing",
      "duration_sec": 3600,
      "calories_kcal": 512,
      "avg_hr": 148,
      "max_hr": 179,
      "distance_m": null
    }
  ],

  "body_measurements": [
    {
      "measured_at": "2026-09-03T07:30:00+05:00",
      "weight_kg": 58.4,
      "body_fat_pct": 23.8,
      "skeletal_muscle_kg": 24.6,
      "height_cm": 168
    }
  ],

  "heart_rate_samples": []
}
```

## Rules the collector must follow

1. **Timestamps are timezone-aware.** RFC3339 with an explicit offset. Naive
   timestamps are rejected with HTTP 422.
2. **`source_uid` is stable.** It must be the same string every time the same
   underlying record is read. This is the whole basis of idempotency.
3. **Missing is `null` or absent — never 0.** A zero step count means you walked
   zero steps. `null` means the watch did not report.
4. **Do not invent fields.** Unknown keys are a 422.
5. **Send overlapping windows freely.** Re-sending the last 7 days daily is the
   expected pattern; duplicates are handled server-side.
6. **HRV must be RMSSD in milliseconds** to go in `hrv_rmssd_ms`. Anything else
   goes elsewhere or gets converted in the collector.

## Response

```json
{
  "accepted": true,
  "inserted": {"sleep_sessions": 7, "daily_metrics": 7, "workouts": 3},
  "updated": {},
  "rejected": [],
  "days_touched": ["2026-08-28", "..."],
  "features_recomputed": 12
}
```

Ingest triggers a feature rebuild from the earliest touched day forward, so the
report is current the moment the POST returns.
