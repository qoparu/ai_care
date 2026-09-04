"""Bot formatting logic, tested without touching Telegram."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bot"))
import telegram_bot as bot  # noqa: E402


def test_checkin_validates_input():
    assert "Usage" in bot.cmd_checkin("")
    assert "integers" in bot.cmd_checkin("a b c")
    assert "between 1 and 5" in bot.cmd_checkin("9 9 9")


def test_unknown_text_is_routed_to_ask(monkeypatch):
    seen = {}

    def fake_ask(question: str) -> str:
        seen["q"] = question
        return "ok"

    monkeypatch.setattr(bot, "cmd_ask", fake_ask)
    assert bot.handle("why is my hrv low") == "ok"
    assert seen["q"] == "why is my hrv low"


def test_unknown_command_returns_help():
    assert "/today" in bot.handle("/nonsense")


def test_trends_refuses_to_claim_a_trend_from_too_few_points(monkeypatch):
    monkeypatch.setattr(
        bot,
        "api_get",
        lambda path, **kw: {
            "window": {"n_days": 30},
            "days": [{"date": "2026-09-01", "hrv_rmssd_ms": 50, "resting_hr": None,
                      "sleep_minutes": None, "recovery": None}],
        },
    )
    out = bot.cmd_trends("")
    assert "no trend claimed" in out


def test_fmt_min():
    assert bot._fmt_min(465) == "7h45"
    assert bot._fmt_min(None) == "n/a"
