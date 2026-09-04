from __future__ import annotations

import logging

from fastapi import FastAPI
from sqlalchemy import select

from app import models
from app.api.routes import router
from app.config import get_settings
from app.db import SessionLocal, engine

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("app")

app = FastAPI(
    title="Personal Health Analytics",
    version="0.1.0",
    description=(
        "Private single-user wellness analytics. Not a medical device. "
        "Metrics are computed by deterministic code; the LLM only interprets them."
    ),
)
app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    # Alembic owns the schema in production (infra/docker-compose runs the
    # migration). create_all keeps a fresh SQLite dev database usable with zero
    # setup; it is a no-op when the tables already exist.
    if settings.database_url.startswith("sqlite"):
        models.Base.metadata.create_all(engine)
    log.info(
        "started: profile=%s tz=%s llm=%s db=%s",
        settings.data_profile,
        settings.timezone,
        settings.llm_provider,
        settings.database_url.split("@")[-1],  # never log credentials
    )


@app.get("/health")
def health() -> dict:
    """Liveness + a data-freshness signal. Contains no health values."""
    with SessionLocal() as db:
        latest = db.execute(
            select(models.DailyFeature.day).order_by(models.DailyFeature.day.desc()).limit(1)
        ).scalar()
        n_days = db.query(models.DailyFeature).count()
    return {
        "status": "ok",
        "data_profile": settings.data_profile,
        "llm_provider": settings.llm_provider,
        "days_with_features": n_days,
        "latest_feature_day": latest,
    }
