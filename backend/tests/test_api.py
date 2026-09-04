from __future__ import annotations

from datetime import date

import pytest

END = date(2026, 9, 3)


def test_auth_is_required(client):
    r = client.get("/api/v1/history", headers={"Authorization": ""})
    assert r.status_code == 401
    r = client.get("/api/v1/history", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_health_endpoint_is_open_and_leaks_no_values(client):
    r = client.get("/health", headers={"Authorization": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) == {
        "status",
        "data_profile",
        "llm_provider",
        "days_with_features",
        "latest_feature_day",
    }


def test_ingest_then_report(client, synthetic_payload):
    r = client.post("/api/v1/ingest", json=synthetic_payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] and body["features_recomputed"] > 0

    r = client.get("/api/v1/report", params={"llm": False})
    assert r.status_code == 200
    rep = r.json()
    assert rep["recovery_score"] is not None
    assert rep["confidence"] in {"LOW", "MEDIUM", "HIGH"}
    assert rep["contributions"]
    assert "not a medical device" in rep["disclaimer"].lower() or "not a diagnosis" in rep["disclaimer"].lower()


def test_empty_payload_is_rejected(client):
    r = client.post("/api/v1/ingest", json={"is_synthetic": True})
    assert r.status_code == 422


def test_naive_timestamp_is_rejected(client):
    r = client.post(
        "/api/v1/ingest",
        json={
            "is_synthetic": True,
            "sleep_sessions": [
                {
                    "source_uid": "x",
                    "start": "2026-09-02T23:00:00",  # no offset
                    "end": "2026-09-03T07:00:00",
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "timezone-aware" in r.text


def test_unknown_field_is_rejected(client):
    r = client.post(
        "/api/v1/ingest",
        json={"is_synthetic": True, "daily_metrics": [{"date": "2026-09-03", "blood_pressure": 120}]},
    )
    assert r.status_code == 422


def test_out_of_range_value_is_rejected(client):
    r = client.post(
        "/api/v1/ingest",
        json={"is_synthetic": True, "daily_metrics": [{"date": "2026-09-03", "resting_hr": 900}]},
    )
    assert r.status_code == 422


def test_synthetic_data_is_refused_in_prod_profile(client, synthetic_payload, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "data_profile", "prod")
    r = client.post("/api/v1/ingest", json=synthetic_payload)
    assert r.status_code == 422
    assert "synthetic" in r.text


def test_checkin_and_recompute(client, synthetic_payload):
    client.post("/api/v1/ingest", json=synthetic_payload)
    latest = client.get("/api/v1/report", params={"llm": False}).json()["date"]
    r = client.post("/api/v1/checkin", json={"date": latest, "energy": 2, "soreness": 4, "mood": 2})
    assert r.status_code == 200 and r.json()["ok"]

    rep = client.get(f"/api/v1/report/{latest}", params={"llm": False}).json()
    assert rep["readiness_score"] < rep["recovery_score"]


def test_ask_without_llm_says_so_instead_of_inventing(client, synthetic_payload):
    client.post("/api/v1/ingest", json=synthetic_payload)
    r = client.post("/api/v1/ask", json={"question": "Why is my recovery low?"})
    assert r.status_code == 200
    assert "not configured" in r.json()["answer"].lower()


def test_export_and_delete(client, synthetic_payload):
    client.post("/api/v1/ingest", json=synthetic_payload)
    exp = client.get("/api/v1/export").json()
    assert exp["sleep_sessions"] and exp["daily_features"]

    assert client.delete("/api/v1/data", params={"confirm": "nope"}).status_code == 400
    r = client.delete("/api/v1/data", params={"confirm": "DELETE-EVERYTHING"})
    assert r.status_code == 200
    assert client.get("/api/v1/export").json()["sleep_sessions"] == []


def test_report_404_for_unknown_day(client):
    assert client.get("/api/v1/report/1999-01-01", params={"llm": False}).status_code == 404
