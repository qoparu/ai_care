#!/usr/bin/env python3
"""Telegram front-end.

Deliberately dependency-free (httpx long-polling, no bot framework): the bot is
a thin client over the analytics API. It never computes a health metric and
never talks to an LLM directly - the backend owns both.

Access control: only user ids in TELEGRAM_ALLOWED_USER_IDS are answered. Every
other update is dropped silently, because a bot token is guessable-adjacent and
this thing serves personal health data.

    python bot/telegram_bot.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import get_settings  # noqa: E402

log = logging.getLogger("bot")
S = get_settings()
API = S.backend_base_url.rstrip("/")
HEADERS = {"Authorization": f"Bearer {S.api_token}"}

HELP = """\
/today — recovery, what changed, what to do
/recovery — the score and its breakdown
/sleep — last 7 nights
/training — load, ACWR, workouts
/trends — 30-day direction of the main metrics
/weight — body measurements
/checkin 4 2 5 — energy, soreness, mood (1-5)
/ask <question> — free-form question about your own data
"""


def api_get(path: str, **params) -> dict | None:
    try:
        r = httpx.get(f"{API}{path}", headers=HEADERS, params=params, timeout=90.0)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("API GET %s failed: %s", path, type(exc).__name__)
        return {"_error": str(type(exc).__name__)}


def api_post(path: str, payload: dict) -> dict | None:
    try:
        r = httpx.post(f"{API}{path}", headers=HEADERS, json=payload, timeout=120.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("API POST %s failed: %s", path, type(exc).__name__)
        return {"_error": str(type(exc).__name__)}


def _fmt_min(m: float | None) -> str:
    if m is None:
        return "n/a"
    return f"{int(m // 60)}h{int(m % 60):02d}"


def cmd_today(_: str) -> str:
    rep = api_get("/api/v1/report")
    if rep is None:
        return "No computed days yet. Sync the collector first."
    if "_error" in rep:
        return f"Backend unreachable ({rep['_error']})."
    head = f"☀️ {rep['date']}\n\n"
    body = rep.get("llm_summary") or rep["deterministic_summary"]
    tail = f"\n\n_{rep['disclaimer']}_"
    return head + body + tail


def cmd_recovery(_: str) -> str:
    rep = api_get("/api/v1/report", llm=False)
    if not rep or "_error" in rep:
        return "No data."
    lines = [
        f"Recovery {rep['recovery_score']}/100 ({rep['band']}) — confidence {rep['confidence']}",
        f"Readiness {rep['readiness_score']}/100",
        "",
        "Contributions:",
    ]
    for c in rep["contributions"]:
        lines.append(f"• {c['component']}: {c['contribution']:+.1f} — {c['detail']}")
    if rep["confidence_reasons"]:
        lines += ["", "Why that confidence:"] + [f"• {r}" for r in rep["confidence_reasons"]]
    return "\n".join(lines)


def cmd_sleep(_: str) -> str:
    h = api_get("/api/v1/history", days=7)
    if not h or not h.get("days"):
        return "No sleep data."
    lines = ["Last 7 nights:"]
    for d in h["days"]:
        eff = f"{d['sleep_efficiency']:.0f}%" if d["sleep_efficiency"] is not None else "n/a"
        lines.append(f"• {d['date']}: {_fmt_min(d['sleep_minutes'])}  eff {eff}")
    observed = [d["sleep_minutes"] for d in h["days"] if d["sleep_minutes"] is not None]
    if observed:
        lines.append(f"\nMean over {len(observed)} measured nights: {_fmt_min(sum(observed)/len(observed))}")
    return "\n".join(lines)


def cmd_training(_: str) -> str:
    h = api_get("/api/v1/history", days=14)
    if not h or not h.get("days"):
        return "No training data."
    lines = ["Last 14 days:"]
    for d in h["days"]:
        load = "n/a" if d["training_load"] is None else f"{d['training_load']:.0f}"
        lines.append(f"• {d['date']}: load {load}")
    last = h["days"][-1]
    if last.get("acwr") is not None:
        verdict = "balanced" if 0.8 <= last["acwr"] <= 1.3 else ("spike" if last["acwr"] > 1.3 else "detraining")
        lines.append(f"\nACWR {last['acwr']:.2f} — {verdict}")
    else:
        lines.append("\nACWR: not enough chronic history yet (needs 14+ days).")
    return "\n".join(lines)


def cmd_trends(_: str) -> str:
    h = api_get("/api/v1/history", days=30)
    if not h or not h.get("days"):
        return "No data."
    days = h["days"]
    out = [f"30-day window ({h['window']['n_days']} days):"]
    for key, label, unit in (
        ("hrv_rmssd_ms", "HRV", "ms"),
        ("resting_hr", "Resting HR", "bpm"),
        ("sleep_minutes", "Sleep", "min"),
        ("recovery", "Recovery", ""),
    ):
        vals = [(d["date"], d[key]) for d in days if d.get(key) is not None]
        if len(vals) < 6:
            out.append(f"• {label}: only {len(vals)} measured days — no trend claimed")
            continue
        half = len(vals) // 2
        first = sum(v for _, v in vals[:half]) / half
        second = sum(v for _, v in vals[half:]) / (len(vals) - half)
        delta = second - first
        arrow = "→" if abs(delta) < abs(first) * 0.03 else ("↑" if delta > 0 else "↓")
        out.append(f"• {label}: {first:.0f} → {second:.0f} {unit} {arrow} (n={len(vals)})")
    out.append("\nFirst half vs second half of the window. Direction, not proof of causation.")
    return "\n".join(out)


def cmd_weight(_: str) -> str:
    h = api_get("/api/v1/history", days=90)
    if not h:
        return "No data."
    pts = [(d["date"], d["weight_kg"]) for d in h.get("days", []) if d.get("weight_kg") is not None]
    if not pts:
        return "No body measurements recorded."
    lines = ["Weight:"] + [f"• {d}: {w:.1f} kg" for d, w in pts[-10:]]
    if len(pts) >= 2:
        lines.append(f"\nChange over {len(pts)} measurements: {pts[-1][1] - pts[0][1]:+.1f} kg")
    return "\n".join(lines)


def cmd_checkin(args: str) -> str:
    parts = args.split()
    if len(parts) < 3:
        return "Usage: /checkin <energy 1-5> <soreness 1-5> <mood 1-5>\nExample: /checkin 4 2 5"
    try:
        energy, soreness, mood = (int(p) for p in parts[:3])
    except ValueError:
        return "All three values must be integers 1-5."
    if not all(1 <= v <= 5 for v in (energy, soreness, mood)):
        return "Values must be between 1 and 5."
    res = api_post(
        "/api/v1/checkin",
        {"date": date.today().isoformat(), "energy": energy, "soreness": soreness, "mood": mood},
    )
    if not res or "_error" in res:
        return "Could not save the check-in."
    return f"Saved for {date.today()}. Readiness recomputed."


def cmd_ask(args: str) -> str:
    if not args.strip():
        return "Ask something, e.g. /ask why is my recovery low this week?"
    res = api_post("/api/v1/ask", {"question": args.strip(), "days": 30})
    if not res or "_error" in res:
        return "Could not reach the backend."
    return res["answer"]


COMMANDS = {
    "/start": lambda _: "Personal health analytics.\n\n" + HELP,
    "/help": lambda _: HELP,
    "/today": cmd_today,
    "/recovery": cmd_recovery,
    "/sleep": cmd_sleep,
    "/training": cmd_training,
    "/trends": cmd_trends,
    "/weight": cmd_weight,
    "/checkin": cmd_checkin,
    "/ask": cmd_ask,
}


def handle(text: str) -> str:
    text = text.strip()
    cmd, _, args = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    handler = COMMANDS.get(cmd)
    if handler is None:
        # Anything that is not a command is treated as a question.
        return cmd_ask(text) if text and not text.startswith("/") else HELP
    return handler(args)


def main() -> int:
    logging.basicConfig(level=S.log_level, format="%(asctime)s %(levelname)s %(message)s")
    token = S.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set", file=sys.stderr)
        return 2
    allowed = S.allowed_telegram_ids
    if not allowed:
        print(
            "TELEGRAM_ALLOWED_USER_IDS is empty. Refusing to start: the bot would "
            "serve your health data to anyone who finds it.",
            file=sys.stderr,
        )
        return 2

    base = f"https://api.telegram.org/bot{token}"
    offset = 0
    log.info("bot started; %d allowed user(s)", len(allowed))

    while True:
        try:
            r = httpx.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 50}, timeout=70.0)
            r.raise_for_status()
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg or "text" not in msg:
                    continue
                uid = msg["from"]["id"]
                if uid not in allowed:
                    log.warning("dropped update from unauthorised user id=%s", uid)
                    continue
                # Log the command only, never the reply: replies contain health data.
                log.info("cmd from %s: %s", uid, msg["text"].split(" ")[0])
                try:
                    reply = handle(msg["text"])
                except Exception:  # noqa: BLE001 - a bot must not die on one bad message
                    log.exception("handler failed")
                    reply = "Something broke handling that. Check the server logs."
                httpx.post(
                    f"{base}/sendMessage",
                    json={"chat_id": msg["chat"]["id"], "text": reply[:4000]},
                    timeout=30.0,
                )
        except httpx.HTTPError as exc:
            log.warning("telegram transport error: %s; retrying in 5s", type(exc).__name__)
            time.sleep(5)
        except KeyboardInterrupt:
            log.info("stopping")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
