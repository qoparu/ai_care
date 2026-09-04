from __future__ import annotations

import logging

from app.config import Settings
from app.llm.base import LLMError, LLMProvider
from app.llm.providers import (
    AnthropicProvider,
    GoogleProvider,
    OllamaProvider,
    OpenAIProvider,
    TemplateProvider,
)

log = logging.getLogger(__name__)


def build_provider(settings: Settings) -> LLMProvider:
    """Return the configured provider, degrading to `template` when unusable.

    Degrading is deliberate: a missing key must never break the morning report,
    because the deterministic report is the source of truth anyway.
    """
    kind = settings.llm_provider
    try:
        if kind == "anthropic":
            if not settings.anthropic_api_key:
                raise LLMError("ANTHROPIC_API_KEY is not set")
            return AnthropicProvider(
                settings.anthropic_api_key,
                settings.llm_model,
                settings.llm_max_output_tokens,
                settings.llm_timeout_s,
            )
        if kind == "openai":
            if not settings.openai_api_key:
                raise LLMError("OPENAI_API_KEY is not set")
            return OpenAIProvider(
                settings.openai_api_key,
                settings.llm_model,
                settings.llm_max_output_tokens,
                settings.llm_timeout_s,
            )
        if kind == "google":
            if not settings.google_api_key:
                raise LLMError("GOOGLE_API_KEY is not set")
            return GoogleProvider(
                settings.google_api_key,
                settings.llm_model,
                settings.llm_max_output_tokens,
                settings.llm_timeout_s,
            )
        if kind == "ollama":
            return OllamaProvider(settings.ollama_base_url, settings.llm_model, settings.llm_timeout_s)
    except LLMError as exc:
        log.warning("LLM provider %s unavailable (%s); falling back to template", kind, exc)
        return TemplateProvider()
    return TemplateProvider()
