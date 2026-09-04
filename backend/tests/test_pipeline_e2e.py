"""End-to-end: synthetic payload -> ingest -> features -> report."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import models
from app.schemas import IngestPayload
from app.services import ingest_service, pipeline, report_service

END = date(2026, 9, 3)


def _ingest(db, settings, payload_dict):
    payload = IngestPayload.model_validate(payload_dict)
    res = ingest_service.ingest(db, payload, tz=settings.timezone)
    pipeline.rebuild(db, settings, start=min(res.days_touched))
    db.commit()
    return res


def test_full_pipeline_produces_scored_days(db, settings, synthetic_payload):
    res = _ingest(db, settings, synthetic_payload)
    assert res.accepted
    rows = db.query(models.DailyFeature).order_by(models.DailyFeature.day).all()
    assert len(rows) >= 40

    scored = [r for r in rows if r.recovery_score is not None]
    # Early days have no baseline yet; later days must be scored.
    assert len(scored) >= 30
    for r in scored:
        assert 0 <= r.recovery_score <= 100
        assert r.confidence in {"LOW", "MEDIUM", "HIGH"}
        assert r.explanation["recovery"]["contributions"]


def test_confidence_grows_with_history(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    rows = [r for r in db.query(models.DailyFeature).order_by(models.DailyFeature.day) if r.recovery_score]
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    assert rank[rows[-1].confidence] >= rank[rows[0].confidence]
    assert rows[0].explanation["confidence"]["baseline_days"] < rows[-1].explanation["confidence"]["baseline_days"]


def test_missing_day_does_not_crash_and_is_not_zero_filled(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    all_days = {date.fromisoformat(m["date"]) for m in synthetic_payload["daily_metrics"]}
    start = min(all_days)
    gap = [d for d in (start + timedelta(days=i) for i in range(45)) if d not in all_days and d <= END]
    assert gap, "generator should leave one day with no data"
    row = db.get(models.DailyFeature, gap[0])
    assert row is not None
    assert row.sleep_minutes is None
    assert row.training_load is None  # unknown, not 0
    assert "training_load" in row.missing_fields["today"]


def test_days_without_hrv_still_score_with_reduced_confidence(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    no_hrv = [m["date"] for m in synthetic_payload["daily_metrics"] if m["hrv_rmssd_ms"] is None]
    assert no_hrv
    row = db.get(models.DailyFeature, date.fromisoformat(no_hrv[-1]))
    assert row.hrv_rmssd_ms is None
    assert row.recovery_score is not None  # other components still carry it
    assert "hrv" not in row.explanation["recovery"]["effective_weights"]
    assert any("missing today" in r for r in row.explanation["confidence"]["reasons"])


def test_ingest_is_idempotent(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    before = {
        "sleep": db.query(models.SleepSession).count(),
        "metrics": db.query(models.DailyMetric).count(),
        "workouts": db.query(models.Workout).count(),
        "raw": db.query(models.RawHealthRecord).count(),
    }
    scores_before = {r.day: r.recovery_score for r in db.query(models.DailyFeature)}

    _ingest(db, settings, synthetic_payload)  # exact same payload again

    after = {
        "sleep": db.query(models.SleepSession).count(),
        "metrics": db.query(models.DailyMetric).count(),
        "workouts": db.query(models.Workout).count(),
        "raw": db.query(models.RawHealthRecord).count(),
    }
    assert before == after
    assert {r.day: r.recovery_score for r in db.query(models.DailyFeature)} == scores_before


def test_rebuild_is_reproducible_from_scratch(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    first = {r.day: (r.recovery_score, r.confidence) for r in db.query(models.DailyFeature)}
    db.query(models.DailyFeature).delete()
    db.commit()
    pipeline.rebuild(db, settings)
    db.commit()
    second = {r.day: (r.recovery_score, r.confidence) for r in db.query(models.DailyFeature)}
    assert first == second


def test_acute_load_spike_shows_up_in_acwr(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    acwrs = [r.acwr for r in db.query(models.DailyFeature).order_by(models.DailyFeature.day) if r.acwr]
    assert acwrs, "ACWR should be computable once 14 chronic days exist"
    assert max(acwrs) > 1.2


def test_report_is_complete_without_any_llm(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    day = db.query(models.DailyFeature.day).order_by(models.DailyFeature.day.desc()).first()[0]
    rep = report_service.get_report(db, day, provider=None, use_llm=False)
    assert rep is not None
    assert rep.llm_summary is None
    assert "Recovery:" in rep.deterministic_summary
    assert "Score breakdown" in rep.deterministic_summary
    assert rep.contributions


def test_llm_payload_contains_no_raw_streams_or_identifiers(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    day = db.query(models.DailyFeature.day).order_by(models.DailyFeature.day.desc()).first()[0]
    row = db.get(models.DailyFeature, day)
    payload = report_service.llm_payload(row, "summary")
    blob = str(payload).lower()
    for forbidden in ("device_id", "source_uid", "synthetic-watch", "heart_rate_samples", "raw"):
        assert forbidden not in blob


def test_checkin_changes_readiness_only(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    day = db.query(models.DailyFeature.day).order_by(models.DailyFeature.day.desc()).first()[0]
    before = db.get(models.DailyFeature, day)
    rec_before, ready_before = before.recovery_score, before.readiness_score

    db.add(models.CheckIn(day=day, energy=1, mood=1, soreness=5))
    db.flush()
    pipeline.rebuild(db, settings, start=day)
    db.commit()

    after = db.get(models.DailyFeature, day)
    assert after.recovery_score == rec_before
    assert after.readiness_score < ready_before


def test_no_data_day_gets_no_score_at_all(db, settings, synthetic_payload):
    _ingest(db, settings, synthetic_payload)
    all_days = {date.fromisoformat(m["date"]) for m in synthetic_payload["daily_metrics"]}
    start = min(all_days)
    gap = [d for d in (start + timedelta(days=i) for i in range(45)) if d not in all_days and d <= END][0]
    row = db.get(models.DailyFeature, gap)
    assert row.recovery_score is None, "a day with no wearable data must not be scored"
    summary = report_service.build_deterministic_summary(row)
    assert "no recovery score" in summary
    assert "RED" not in summary
