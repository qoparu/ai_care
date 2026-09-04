"""Report assembly.

The deterministic report is built entirely from daily_features. The LLM is an
optional layer on top; if it fails, refuses, or is not configured, the user
still gets a complete, correct report.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.llm.base import LLMError, LLMProvider
from app.llm.prompts import SYSTEM_ASK, SYSTEM_DAILY
from app.analytics.recovery import NEUTRAL
from app.schemas import ContributionOut, DailyReportOut

log = logging.getLogger(__name__)

# Guidance is rule-based, keyed off recovery band. The LLM may rephrase these
# but has no authority to invent different advice.
BAND_GUIDANCE: dict[str, list[str]] = {
    "GREEN": [
        "Hard session (intervals / heavy strength / sparring) — fine",
        "Long endurance — fine",
        "Anything you had planned — go",
    ],
    "YELLOW": [
        "Moderate strength or technique work — fine",
        "Hard intervals — possible, but cut the volume",
        "Long easy aerobic — good option",
    ],
    "ORANGE": [
        "Moderate strength — okay, drop the top sets",
        "HIIT / sparring — probably skip",
        "Easy activity, walking, mobility — good option",
    ],
    "RED": [
        "Hard training — skip",
        "Light movement, walking, stretching — okay",
        "Prioritise sleep over the session",
    ],
}


def _fmt_min(m: float | None) -> str:
    if m is None:
        return "n/a"
    sign = "-" if m < 0 else ""
    m = abs(m)
    return f"{sign}{int(m // 60)}h{int(m % 60):02d}"


def build_deterministic_summary(row: models.DailyFeature) -> str:
    exp = row.explanation or {}
    dev = exp.get("deviations", {})
    conf = exp.get("confidence", {})
    rec = exp.get("recovery", {})
    band = rec.get("band")
    emoji = rec.get("band_emoji") or ""

    lines: list[str] = []
    if row.recovery_score is None:
        lines.append(f"{row.day}: no recovery score — not enough data to compute one honestly.")
        for note in rec.get("notes", []):
            lines.append(f"• {note}")
        for reason in conf.get("reasons", []):
            lines.append(f"• {reason}")
        missing_today = (row.missing_fields or {}).get("today", [])
        if missing_today:
            lines.append(f"• not measured today: {', '.join(missing_today)}")
        return "\n".join(lines)

    lines.append(f"Recovery: {row.recovery_score:.0f}/100 {emoji} ({band})")
    if row.readiness_score is not None and abs(row.readiness_score - row.recovery_score) >= 0.5:
        lines.append(f"Readiness: {row.readiness_score:.0f}/100 (recovery adjusted by check-in / load)")
    lines.append(f"Confidence: {row.confidence}")

    lines.append("")
    lines.append("What changed:")
    changed = False
    if dev.get("hrv_pct") is not None:
        lines.append(f"• HRV {row.hrv_rmssd_ms:.0f} ms — {dev['hrv_pct']:+.0f}% vs baseline")
        changed = True
    if dev.get("resting_hr_bpm") is not None:
        lines.append(f"• Resting HR {row.resting_hr:.0f} bpm — {dev['resting_hr_bpm']:+.0f} bpm vs baseline")
        changed = True
    if dev.get("sleep_minutes") is not None:
        lines.append(
            f"• Sleep {_fmt_min(row.sleep_minutes)} — {_fmt_min(dev['sleep_minutes'])} vs baseline"
            + (f" ({dev['sleep_pct']:+.0f}%)" if dev.get("sleep_pct") is not None else "")
        )
        changed = True
    if row.sleep_debt_minutes:
        lines.append(f"• Sleep debt (7d): {_fmt_min(row.sleep_debt_minutes)}")
        changed = True
    if row.acwr is not None:
        lines.append(f"• Acute:chronic load ratio {row.acwr:.2f}")
        changed = True
    if not changed:
        lines.append("• nothing deviates enough from baseline to report")

    lines.append("")
    lines.append(f"Score breakdown (points away from your normal, {NEUTRAL:.0f}):")
    for c in rec.get("contributions", []):
        lines.append(f"• {c['component']}: {c['contribution']:+.1f}  ({c['detail']})")

    if band in BAND_GUIDANCE:
        lines.append("")
        lines.append("Today:")
        lines.extend(f"• {g}" for g in BAND_GUIDANCE[band])

    reasons = conf.get("reasons", [])
    if reasons:
        lines.append("")
        lines.append("Confidence notes:")
        lines.extend(f"• {r}" for r in reasons)

    missing = (row.missing_fields or {}).get("today", [])
    if missing:
        lines.append(f"• not measured today: {', '.join(missing)}")

    return "\n".join(lines)


def llm_payload(row: models.DailyFeature, summary: str) -> dict:
    """The ONLY thing sent to an external LLM.

    Derived features and deviations. No raw sensor streams, no device ids, no
    timestamps beyond the date, no identifiers.
    """
    exp = row.explanation or {}
    return {
        "date": row.day.isoformat(),
        "recovery_score": row.recovery_score,
        "readiness_score": row.readiness_score,
        "band": (exp.get("recovery") or {}).get("band"),
        "confidence": row.confidence,
        "confidence_reasons": (exp.get("confidence") or {}).get("reasons", []),
        "deviations": exp.get("deviations", {}),
        "contributions": (exp.get("recovery") or {}).get("contributions", []),
        "features": {
            "sleep_minutes": row.sleep_minutes,
            "sleep_efficiency": row.sleep_efficiency,
            "deep_sleep_minutes": row.deep_sleep_minutes,
            "rem_sleep_minutes": row.rem_sleep_minutes,
            "sleep_debt_minutes": row.sleep_debt_minutes,
            "resting_hr": row.resting_hr,
            "hrv_rmssd_ms": row.hrv_rmssd_ms,
            "steps": row.steps,
            "active_calories": row.active_calories,
            "workout_minutes": row.workout_minutes,
            "training_load": row.training_load,
            "acwr": row.acwr,
        },
        "missing_fields": (row.missing_fields or {}).get("today", []),
        "rule_based_guidance": BAND_GUIDANCE.get((exp.get("recovery") or {}).get("band") or "", []),
        "deterministic_summary": summary,
    }


def get_report(
    db: Session,
    day: Date,
    *,
    provider: LLMProvider | None = None,
    use_llm: bool = True,
) -> DailyReportOut | None:
    row = db.get(models.DailyFeature, day)
    if row is None:
        return None

    summary = build_deterministic_summary(row)
    exp = row.explanation or {}
    out = DailyReportOut(
        date=row.day,
        recovery_score=row.recovery_score,
        readiness_score=row.readiness_score,
        band=(exp.get("recovery") or {}).get("band"),
        confidence=row.confidence or "LOW",  # type: ignore[arg-type]
        confidence_reasons=(exp.get("confidence") or {}).get("reasons", []),
        contributions=[ContributionOut(**c) for c in (exp.get("recovery") or {}).get("contributions", [])],
        features=llm_payload(row, summary)["features"],
        deviations=exp.get("deviations", {}),
        missing_fields=(row.missing_fields or {}).get("today", []),
        deterministic_summary=summary,
    )

    if use_llm and provider is not None and provider.name != "template":
        try:
            resp = provider.generate(SYSTEM_DAILY, llm_payload(row, summary))
            if resp.refused or not resp.text:
                log.warning("LLM returned no usable text (refused=%s); using deterministic report", resp.refused)
            else:
                out.llm_summary = resp.text
                out.llm_provider = f"{resp.provider}:{resp.model}"
        except LLMError as exc:
            log.warning("LLM failed (%s); using deterministic report", exc)
    return out


def history_context(db: Session, days: int = 30, end: Date | None = None) -> dict:
    """Compact structured extract for free-form questions."""
    latest = end or db.execute(select(models.DailyFeature.day).order_by(models.DailyFeature.day.desc()).limit(1)).scalar()
    if latest is None:
        return {"days": [], "note": "no data"}
    start = latest - timedelta(days=days - 1)
    rows = (
        db.execute(
            select(models.DailyFeature)
            .where(models.DailyFeature.day >= start, models.DailyFeature.day <= latest)
            .order_by(models.DailyFeature.day)
        )
        .scalars()
        .all()
    )
    return {
        "window": {"start": start.isoformat(), "end": latest.isoformat(), "n_days": len(rows)},
        "days": [
            {
                "date": r.day.isoformat(),
                "recovery": r.recovery_score,
                "readiness": r.readiness_score,
                "confidence": r.confidence,
                "sleep_minutes": r.sleep_minutes,
                "sleep_efficiency": r.sleep_efficiency,
                "resting_hr": r.resting_hr,
                "hrv_rmssd_ms": r.hrv_rmssd_ms,
                "steps": r.steps,
                "training_load": r.training_load,
                "acwr": r.acwr,
                "weight_kg": r.weight_kg,
            }
            for r in rows
        ],
        "latest_baselines": (rows[-1].explanation or {}).get("baselines", {}) if rows else {},
    }


def answer_question(db: Session, question: str, provider: LLMProvider, *, days: int = 30) -> str:
    ctx = history_context(db, days=days)
    if provider.name == "template":
        return (
            "LLM is not configured, so free-form questions are unavailable.\n"
            "Set LLM_PROVIDER and the matching API key in .env.\n"
            f"Structured data for the last {ctx.get('window', {}).get('n_days', 0)} days is available via /api/v1/history."
        )
    try:
        resp = provider.generate(SYSTEM_ASK, ctx, question)
    except LLMError as exc:
        return f"LLM unavailable ({exc}). The structured data is still in the database."
    if resp.refused or not resp.text:
        return "The model declined to answer that. Rephrase it as a question about your own metrics."
    return resp.text
