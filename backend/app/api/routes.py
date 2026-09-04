from __future__ import annotations

import logging
from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.deps import get_provider, require_token
from app.config import Settings, get_settings
from app.db import get_db
from app.llm.base import LLMProvider
from app.schemas import CheckInIn, DailyReportOut, IngestPayload, IngestResult
from app.services import ingest_service, pipeline, report_service

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])


@router.post("/ingest", response_model=IngestResult)
def ingest(
    payload: IngestPayload,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IngestResult:
    if payload.is_synthetic and settings.data_profile == "prod":
        raise HTTPException(
            status_code=422,
            detail="synthetic payload rejected: DATA_PROFILE=prod holds real data only",
        )
    if payload.record_count() == 0:
        raise HTTPException(status_code=422, detail="empty payload")

    result = ingest_service.ingest(db, payload, tz=payload.timezone or settings.timezone)
    if result.days_touched:
        result.features_recomputed = pipeline.rebuild(db, settings, start=min(result.days_touched))
    db.commit()
    return result


@router.post("/checkin")
def checkin(
    body: CheckInIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    row = db.get(models.CheckIn, body.date)
    data = body.model_dump(exclude={"date"})
    if row is None:
        db.add(models.CheckIn(day=body.date, **data))
    else:
        for k, v in data.items():
            if v is not None:
                setattr(row, k, v)
    db.flush()
    recomputed = pipeline.rebuild(db, settings, start=body.date)
    db.commit()
    return {"ok": True, "date": body.date, "features_recomputed": recomputed}


@router.get("/report/{day}", response_model=DailyReportOut)
def report(
    day: Date,
    llm: bool = Query(default=True, description="attach the LLM interpretation"),
    db: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_provider),
) -> DailyReportOut:
    out = report_service.get_report(db, day, provider=provider, use_llm=llm)
    if out is None:
        raise HTTPException(status_code=404, detail=f"no computed features for {day}")
    return out


@router.get("/report", response_model=DailyReportOut)
def latest_report(
    llm: bool = Query(default=True),
    db: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_provider),
) -> DailyReportOut:
    day = db.execute(
        select(models.DailyFeature.day)
        .where(models.DailyFeature.recovery_score.is_not(None))
        .order_by(models.DailyFeature.day.desc())
        .limit(1)
    ).scalar()
    if day is None:
        raise HTTPException(status_code=404, detail="no computed features yet")
    out = report_service.get_report(db, day, provider=provider, use_llm=llm)
    assert out is not None
    return out


@router.get("/history")
def history(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    return report_service.history_context(db, days=days)


@router.get("/features/{day}")
def features(day: Date, db: Session = Depends(get_db)) -> dict:
    row = db.get(models.DailyFeature, day)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no features for {day}")
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


@router.post("/ask")
def ask(
    question: str = Body(..., embed=True, max_length=1000),
    days: int = Body(default=30, embed=True, ge=1, le=365),
    db: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_provider),
) -> dict:
    answer = report_service.answer_question(db, question, provider, days=days)
    return {"answer": answer, "provider": provider.name}


@router.post("/recompute")
def recompute(
    start: Date | None = Body(default=None, embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    n = pipeline.rebuild(db, settings, start=start)
    db.commit()
    return {"rows": n}


@router.get("/export")
def export_all(db: Session = Depends(get_db)) -> dict:
    """Full personal data export (GDPR-style right to portability)."""
    def dump(model):  # type: ignore[no-untyped-def]
        return [
            {c.key: getattr(r, c.key) for c in r.__table__.columns}
            for r in db.execute(select(model)).scalars()
        ]

    return {
        "sleep_sessions": dump(models.SleepSession),
        "daily_metrics": dump(models.DailyMetric),
        "workouts": dump(models.Workout),
        "body_measurements": dump(models.BodyMeasurement),
        "checkins": dump(models.CheckIn),
        "daily_features": dump(models.DailyFeature),
    }


@router.delete("/data")
def delete_all(
    confirm: str = Query(..., description="must be the literal string DELETE-EVERYTHING"),
    db: Session = Depends(get_db),
) -> dict:
    """Right to erasure. Deliberately explicit and deliberately irreversible."""
    if confirm != "DELETE-EVERYTHING":
        raise HTTPException(status_code=400, detail="confirmation string mismatch")
    counts = {}
    for model in (
        models.DailyFeature,
        models.CheckIn,
        models.BodyMeasurement,
        models.Workout,
        models.HeartRateSample,
        models.DailyMetric,
        models.SleepSession,
        models.RawHealthRecord,
    ):
        counts[model.__tablename__] = db.query(model).delete()
    db.commit()
    log.warning("all personal data deleted: %s", counts)
    return {"deleted": counts}
