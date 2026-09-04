from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Must be set before app.config / app.db are imported anywhere.
_TMP = Path(tempfile.mkdtemp(prefix="health-test-"))
os.environ.update(
    DATABASE_URL=f"sqlite+pysqlite:///{_TMP / 'test.db'}",
    API_TOKEN="test-token",
    DATA_PROFILE="dev",
    TIMEZONE="Asia/Almaty",
    SEX="female",
    BIRTH_YEAR="2002",
    LLM_PROVIDER="template",
)


@pytest.fixture(scope="session")
def settings():
    from app.config import get_settings

    return get_settings()


@pytest.fixture()
def db(settings):
    from app import models
    from app.db import SessionLocal, engine

    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-token"})
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def synthetic_payload():
    import sys
    from datetime import date

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    from generate_synthetic import generate

    return generate(days=45, tz="Asia/Almaty", seed=7, end=date(2026, 9, 3))
