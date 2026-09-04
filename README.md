# Personal Health Analytics

A private, single-user analytics system: wearable data in, a transparent daily
recovery/readiness score out, with an LLM that explains the numbers and is
structurally prevented from inventing them.

**Not a medical device. Not a diagnostic system.** Every number is a wellness
estimate derived from consumer wearable data.

---

## Status

| Piece | State |
|---|---|
| Ingestion contract + validation | ✅ working, tested |
| FastAPI backend + PostgreSQL/SQLite | ✅ working, tested |
| Feature engine (sleep, cardio, load, body) | ✅ working, tested |
| Personal baseline (robust, trailing) | ✅ working, tested |
| Recovery + readiness score, fully explainable | ✅ working, tested |
| Confidence model | ✅ working, tested |
| LLM interpretation layer (4 providers + no-key fallback) | ✅ working |
| Telegram bot | ✅ working (needs a token) |
| Synthetic data generator | ✅ working |
| **Android Samsung Health collector** | ⚠️ **skeleton only — see below** |

64 tests pass. `python -m pytest backend/tests -q`

### About the Android collector

It is a skeleton, not a working app, and this is stated rather than glossed:
building it requires a physical Galaxy Watch 7, a phone with Samsung Health, and
Samsung Health Data SDK developer mode. None of that can be verified from a
server, so shipping untested Kotlin as "done" would be a lie.

Everything downstream of the collector is complete and proven end-to-end against
the synthetic generator, so the collector has an exact, tested target to hit:
`docs/INGESTION_CONTRACT.md`.

Two routes to real data, both viable for personal use without Samsung partner
approval:

1. **Samsung Health Data SDK + developer mode** — full data surface including
   Samsung-specific metrics. Verify current requirements at
   <https://developer.samsung.com/health/data/guide/developer-mode.html>.
2. **Health Connect** — no approval needed at all, but exposes a subset
   (sleep stages, HR, steps, exercise, body composition; Samsung's proprietary
   Energy Score likely not).

The backend does not care which one you pick.

---

## Run it in two minutes

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env          # then set API_TOKEN

cd backend && uvicorn app.main:app --reload &

# 45 days of synthetic data, ingested and scored
python tools/generate_synthetic.py --days 45 \
  --post http://localhost:8000 --token "$API_TOKEN"

curl -H "Authorization: Bearer $API_TOKEN" \
  http://localhost:8000/api/v1/report | jq -r .deterministic_summary
```

Output:

```
Recovery: 73/100 🟡 (YELLOW)
Confidence: MEDIUM

What changed:
• HRV 58 ms — +7% vs baseline
• Resting HR 60 bpm — +1 bpm vs baseline
• Sleep 7h10 — -0h10 vs baseline (-2%)
• Sleep debt (7d): 8h31
• Acute:chronic load ratio 1.12

Score breakdown (points away from your normal, 72):
• resting_hr: -1.0  (resting HR 60 bpm, z=+0.37 vs 28d baseline)
• sleep: -0.6  (duration z=-0.25; efficiency z=+0.40; Samsung sleep score=61)
• load: +0.7  (yesterday load z=-0.45 vs 28d baseline; ACWR=1.12)
• hrv: +2.2  (HRV 58 ms, z=+0.57 vs 26d baseline)

Today:
• Moderate strength or technique work — fine
• Hard intervals — possible, but cut the volume
• Long easy aerobic — good option

Confidence notes:
• personal baseline is 26 days
```

Docker instead:

```bash
cp .env.example .env    # set API_TOKEN and POSTGRES_PASSWORD
docker compose -f infra/docker-compose.yml up -d          # api + postgres
docker compose -f infra/docker-compose.yml --profile bot up -d   # + telegram
```

---

## Architecture

```
Galaxy Watch 7 → Samsung Health → [Android collector]
                                        │ HTTPS + bearer token
                                        ▼
                              FastAPI  ──  PostgreSQL
                                        │
                       raw → normalized → daily_features
                                        │
                    baseline → recovery/readiness → confidence
                                        │
                              LLM interpretation (optional)
                                        │
                              Telegram bot / API
```

**The LLM never calculates a health metric.** Python computes every number; the
LLM receives a small structured feature payload and writes prose about it. If
the LLM is absent, fails, or refuses, the deterministic report is returned in
full — it is the source of truth, not a fallback.

---

## What makes the numbers trustworthy

These are enforced by tests, not by good intentions:

- **Missing is never zero.** A day with no data produces `NULL`, not `0`.
  `training_load = 0` means "activity synced, no workout"; `NULL` means "unknown".
- **Today is excluded from its own baseline.**
- **Robust statistics.** Median and MAD, so one broken night does not redefine
  normal. Scale has a floor so a flat series cannot produce infinite z-scores.
- **Components with no data are dropped, not imputed.** Weights renormalize.
- **Below 40% weight coverage, no score is emitted at all.** An early version
  called a no-data day "RED — skip training" from one component; there is now a
  regression test for that.
- **Every score decomposes.** Contributions sum to `score - 72`.
- **Confidence is evidence-based**, not vibes: baseline size, missingness,
  coverage, weight covered — each demotion carries a stated reason.
- **Rebuilds are reproducible.** Drop `daily_features`, recompute, get identical
  rows.

Full definitions: [`docs/METRICS.md`](docs/METRICS.md).

---

## Privacy

- Bearer-token auth on every data endpoint, constant-time comparison.
- Postgres and the API bind to `127.0.0.1` in Compose. Put TLS in front before
  the phone talks to it over anything but a VPN or your own LAN.
- **No health values in logs.** Ingestion logs record counts; the bot logs the
  command name, never the reply.
- **Minimal LLM payload.** Only derived features and deviations leave the
  machine — no raw sensor streams, no device ids, no `source_uid`s. There is a
  test asserting this.
- `LLM_PROVIDER=ollama` keeps everything local; `template` uses no LLM at all.
- `GET /api/v1/export` for full portability, `DELETE /api/v1/data` for erasure.
- `.env` is gitignored. Nothing else may hold a secret.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/ingest` | collector payload; triggers feature rebuild |
| `GET /api/v1/report` / `/report/{day}` | full report, `?llm=false` to skip the LLM |
| `GET /api/v1/features/{day}` | raw feature row |
| `GET /api/v1/history?days=30` | compact series |
| `POST /api/v1/checkin` | subjective energy / soreness / mood |
| `POST /api/v1/ask` | free-form question over your own data |
| `POST /api/v1/recompute` | rebuild features |
| `GET /api/v1/export` · `DELETE /api/v1/data` | portability / erasure |
| `GET /health` | liveness + freshness, no health values |

Telegram: `/today` `/recovery` `/sleep` `/training` `/trends` `/weight`
`/checkin 4 2 5` `/ask <question>`

---

## Layout

```
backend/app/
  analytics/   baseline · features · recovery · confidence   ← all the maths
  llm/         provider-agnostic interface + 4 providers
  services/    ingest · pipeline · report
  api/         routes, auth
bot/           telegram front-end
tools/         synthetic data generator
docs/          METRICS · DATA_MODEL · INGESTION_CONTRACT · ROADMAP
infra/         docker-compose · Dockerfile
android/       collector skeleton (not functional yet)
```

---

## Next

See [`docs/ROADMAP.md`](docs/ROADMAP.md). Short version: build the collector,
get 14 real days, then re-tune the weights in `recovery.py` against data instead
of against assumptions.
