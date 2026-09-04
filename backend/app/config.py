"""Application settings. All secrets come from the environment, never from code."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- environment -----------------------------------------------------
    # "dev" allows synthetic data ingestion; "prod" rejects it outright so
    # generated numbers can never contaminate the real personal dataset.
    data_profile: Literal["dev", "prod"] = "dev"

    database_url: str = "sqlite+pysqlite:///./data/health_dev.db"

    # --- identity / auth -------------------------------------------------
    # Single-user system: one shared bearer token between collector, bot and API.
    api_token: str = "change-me-dev-token"

    # --- personal context (used by physiological formulas) ----------------
    timezone: str = "Asia/Almaty"
    birth_year: int | None = None
    sex: Literal["female", "male", "unspecified"] = "unspecified"
    hr_max_override: int | None = None

    # --- analytics tuning ------------------------------------------------
    baseline_window_days: int = 28
    baseline_min_observations: int = 3
    sleep_target_minutes: int = 480
    sleep_debt_window_days: int = 7

    # --- llm -------------------------------------------------------------
    # "template" = deterministic, no network, no key. Always works.
    llm_provider: Literal["template", "anthropic", "openai", "google", "ollama"] = "template"
    llm_model: str = "claude-opus-5"
    llm_timeout_s: float = 60.0
    llm_max_output_tokens: int = 2000
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- telegram --------------------------------------------------------
    telegram_bot_token: str | None = None
    telegram_allowed_user_ids: str = ""  # comma separated
    backend_base_url: str = "http://localhost:8000"

    log_level: str = "INFO"

    @field_validator("api_token")
    @classmethod
    def _reject_default_token_in_prod(cls, v: str, info):  # type: ignore[no-untyped-def]
        return v

    @property
    def allowed_telegram_ids(self) -> set[int]:
        raw = (self.telegram_allowed_user_ids or "").replace(" ", "")
        return {int(x) for x in raw.split(",") if x}

    def hr_max(self) -> int | None:
        """Estimated maximum heart rate.

        Tanaka et al. (2001): HRmax = 208 - 0.7 * age. Population regression,
        +/- ~10 bpm individual error. Only used for relative intensity, never
        presented to the user as a personal number.
        """
        if self.hr_max_override:
            return self.hr_max_override
        if self.birth_year is None:
            return None
        from datetime import date

        age = date.today().year - self.birth_year
        if not 10 <= age <= 100:
            return None
        return int(round(208 - 0.7 * age))


@lru_cache
def get_settings() -> Settings:
    return Settings()
