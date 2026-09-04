#!/usr/bin/env python3
"""Generate a synthetic health dataset matching the ingestion contract.

Purpose: prove the pipeline end-to-end before a single real byte exists, and
give the analytics code something to be tested against. Every record is flagged
`is_synthetic`, and the backend refuses synthetic payloads when DATA_PROFILE=prod.

  python tools/generate_synthetic.py --days 45 > payload.json
  python tools/generate_synthetic.py --days 45 --post http://localhost:8000 --token dev

The generator deliberately injects the messy cases the pipeline must survive:
  * two days with no HRV reading at all
  * one day with no data whatsoever (watch not worn)
  * one very short night followed by a hard workout
  * a training-load ramp that pushes ACWR above 1.5
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ_DEFAULT = "Asia/Almaty"

WORKOUT_PLAN = {  # weekday -> (type, minutes, relative intensity)
    0: ("strength", 55, 0.72),
    1: ("boxing", 60, 0.85),
    3: ("running", 40, 0.80),
    5: ("boxing", 75, 0.88),
}


def generate(days: int, tz: str, seed: int, end: date | None = None) -> dict:
    rng = random.Random(seed)
    zone = ZoneInfo(tz)
    end = end or date.today()
    start = end - timedelta(days=days - 1)

    hrv_base, rhr_base, sleep_base = 58.0, 57.0, 452.0

    sleep_sessions, daily_metrics, workouts, body = [], [], [], []

    no_data_day = start + timedelta(days=days // 3)
    no_hrv_days = {start + timedelta(days=days // 2), start + timedelta(days=days // 2 + 3)}
    bad_night = start + timedelta(days=days - 4)
    ramp_start = days - 8

    prev_load = 0.0
    for i in range(days):
        day = start + timedelta(days=i)
        if day == no_data_day:
            continue  # watch not worn: the pipeline must not crash or zero-fill

        # Slow drift so a baseline actually has something to track.
        drift = 3.0 * math.sin(i / 9.0)
        # Yesterday's training suppresses HRV and raises resting HR today.
        load_penalty = min(12.0, prev_load / 12.0)

        is_bad = day == bad_night
        sleep_min = sleep_base + drift * 4 + rng.gauss(0, 26)
        if is_bad:
            sleep_min = 268.0
        sleep_min = max(180.0, min(620.0, sleep_min))

        sleep_deficit_effect = (sleep_base - sleep_min) / 30.0
        hrv = hrv_base + drift + rng.gauss(0, 3.4) - load_penalty - sleep_deficit_effect * 1.6
        rhr = rhr_base - drift * 0.35 + rng.gauss(0, 1.4) + load_penalty * 0.35 + sleep_deficit_effect * 0.5

        bedtime_hour = 23 + rng.gauss(0, 0.7) + (1.5 if is_bad else 0)
        bed_dt = datetime.combine(day - timedelta(days=1), time(0, 0), tzinfo=zone) + timedelta(
            hours=min(26.5, max(21.0, bedtime_hour))
        )
        wake_dt = bed_dt + timedelta(minutes=sleep_min + rng.uniform(18, 46))
        total_in_bed = (wake_dt - bed_dt).total_seconds() / 60.0
        awake = total_in_bed - sleep_min
        deep = sleep_min * rng.uniform(0.13, 0.20)
        rem = sleep_min * rng.uniform(0.19, 0.26)
        light = sleep_min - deep - rem

        sleep_sessions.append(
            {
                "source_uid": f"syn-sleep-{day.isoformat()}",
                "start": bed_dt.isoformat(),
                "end": wake_dt.isoformat(),
                "duration_min": round(total_in_bed, 1),
                "actual_sleep_min": round(sleep_min, 1),
                "awake_min": round(awake, 1),
                "deep_min": round(deep, 1),
                "rem_min": round(rem, 1),
                "light_min": round(light, 1),
                "sleep_efficiency": round(sleep_min / total_in_bed * 100, 1),
                "sleep_score": round(max(20.0, min(100.0, 55 + (sleep_min - 400) / 5)), 0),
                "avg_hr": round(rhr + rng.uniform(1.5, 5.0), 1),
                "device_id": "synthetic-watch",
            }
        )

        # --- workouts -----------------------------------------------------
        today_load = 0.0
        plan = WORKOUT_PLAN.get(day.weekday())
        if plan and rng.random() > 0.12:
            wtype, wmin, intensity = plan
            if i >= ramp_start:  # deliberate acute-load spike near the end
                wmin = int(wmin * 1.5)
                intensity = min(0.95, intensity + 0.06)
            hr_max_est = 194
            avg_hr = rhr + (hr_max_est - rhr) * intensity + rng.gauss(0, 3)
            start_dt = datetime.combine(day, time(19, 0), tzinfo=zone) + timedelta(minutes=rng.randint(-90, 90))
            workouts.append(
                {
                    "source_uid": f"syn-wo-{day.isoformat()}",
                    "started_at": start_dt.isoformat(),
                    "ended_at": (start_dt + timedelta(minutes=wmin)).isoformat(),
                    "exercise_type": wtype,
                    "duration_sec": wmin * 60,
                    "calories_kcal": round(wmin * intensity * 9.5, 0),
                    "avg_hr": round(avg_hr, 1),
                    "max_hr": round(min(hr_max_est, avg_hr + rng.uniform(12, 25)), 1),
                    "distance_m": round(wmin * 190.0, 0) if wtype == "running" else None,
                }
            )
            today_load = wmin * intensity * 1.6
        prev_load = today_load

        steps = int(max(1200, rng.gauss(9200, 2400) + (2600 if plan else 0)))
        daily_metrics.append(
            {
                "date": day.isoformat(),
                "resting_hr": round(rhr, 1),
                "avg_hr": round(rhr + rng.uniform(12, 20), 1),
                "min_hr": round(rhr - rng.uniform(2, 6), 1),
                "max_hr": round(rhr + rng.uniform(60, 110), 1),
                "sleeping_hr": round(rhr + rng.uniform(1, 4), 1),
                "hrv_rmssd_ms": None if day in no_hrv_days else round(max(12.0, hrv), 1),
                "steps": steps,
                "active_kcal": round(steps * 0.042 + today_load * 3.1, 0),
                "energy_score": round(max(10.0, min(100.0, 60 + (hrv - hrv_base) * 1.8)), 0),
            }
        )

        if day.weekday() == 0:
            body.append(
                {
                    "measured_at": datetime.combine(day, time(7, 30), tzinfo=zone).isoformat(),
                    "weight_kg": round(58.0 + math.sin(i / 20.0) * 0.9 + rng.gauss(0, 0.25), 2),
                    "body_fat_pct": round(24.0 + rng.gauss(0, 0.5), 1),
                    "skeletal_muscle_kg": round(24.5 + rng.gauss(0, 0.2), 2),
                    "height_cm": 168.0,
                }
            )

    return {
        "collector_version": "synthetic-generator/1.0",
        "device_id": "synthetic-watch",
        "source_package": "synthetic",
        "timezone": tz,
        "is_synthetic": True,
        "sleep_sessions": sleep_sessions,
        "heart_rate_samples": [],
        "daily_metrics": daily_metrics,
        "workouts": workouts,
        "body_measurements": body,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--tz", default=TZ_DEFAULT)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--end", type=date.fromisoformat, default=None, help="last day (YYYY-MM-DD)")
    ap.add_argument("--post", metavar="BASE_URL", help="POST to a running backend instead of stdout")
    ap.add_argument("--token", default=None, help="bearer token for --post")
    args = ap.parse_args()

    payload = generate(args.days, args.tz, args.seed, args.end)

    if not args.post:
        json.dump(payload, sys.stdout, indent=2)
        print()
        return 0

    import httpx

    if not args.token:
        print("--token is required with --post", file=sys.stderr)
        return 2
    r = httpx.post(
        f"{args.post.rstrip('/')}/api/v1/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=120.0,
    )
    print(r.status_code)
    print(json.dumps(r.json(), indent=2, default=str))
    return 0 if r.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
