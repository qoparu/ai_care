"""Concrete providers.

Anthropic uses the official SDK. The rest use raw HTTP because pinning four
vendor SDKs into a single-user side project is not worth the dependency
surface. `template` is the always-available deterministic fallback: no key,
no network, no hallucination risk.
"""
from __future__ import annotations

import logging

import httpx

from app.llm.base import LLMError, LLMProvider, LLMResponse

log = logging.getLogger(__name__)


class TemplateProvider(LLMProvider):
    """No LLM at all. Returns the deterministic summary the code already built.

    This exists so the whole system is usable with zero API keys, and so every
    LLM answer has a truthful fallback when a provider is down or refuses.
    """

    name = "template"

    def generate(self, system_prompt: str, payload: dict, user_message: str | None = None) -> LLMResponse:
        text = payload.get("deterministic_summary") or (
            "LLM is not configured. The structured result is available in the API response."
        )
        return LLMResponse(text=text, provider=self.name, model=None)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int, timeout: float) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise LLMError("anthropic SDK not installed: pip install anthropic") from exc
        self._client = Anthropic(api_key=api_key, timeout=timeout)
        self.model = model
        self.max_tokens = max_tokens

    def generate(self, system_prompt: str, payload: dict, user_message: str | None = None) -> LLMResponse:
        content = self.render_payload(payload, user_message)
        messages = [{"role": "user", "content": content}]
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=messages,
        )
        try:
            # Server-side fallback keeps a health-adjacent prompt from dead-ending
            # on a safety refusal. Older SDKs lack it; fall back to plain create.
            resp = self._client.beta.messages.create(
                **kwargs,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except (AttributeError, TypeError):
            resp = self._client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - surface provider errors uniformly
            raise LLMError(f"anthropic request failed: {type(exc).__name__}") from exc

        if getattr(resp, "stop_reason", None) == "refusal":
            return LLMResponse(text="", provider=self.name, model=self.model, refused=True)

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()
        return LLMResponse(text=text, provider=self.name, model=self.model)


class _HTTPProvider(LLMProvider):
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def _post(self, url: str, *, headers: dict, json_body: dict) -> dict:
        try:
            r = httpx.post(url, headers=headers, json=json_body, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"{self.name} HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.name} transport error: {type(exc).__name__}") from exc


class OpenAIProvider(_HTTPProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, max_tokens: int, timeout: float) -> None:
        super().__init__(timeout)
        self.api_key, self.model, self.max_tokens = api_key, model, max_tokens

    def generate(self, system_prompt: str, payload: dict, user_message: str | None = None) -> LLMResponse:
        data = self._post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json_body={
                "model": self.model,
                "max_completion_tokens": self.max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": self.render_payload(payload, user_message)},
                ],
            },
        )
        text = data["choices"][0]["message"]["content"] or ""
        return LLMResponse(text=text.strip(), provider=self.name, model=self.model)


class GoogleProvider(_HTTPProvider):
    name = "google"

    def __init__(self, api_key: str, model: str, max_tokens: int, timeout: float) -> None:
        super().__init__(timeout)
        self.api_key, self.model, self.max_tokens = api_key, model, max_tokens

    def generate(self, system_prompt: str, payload: dict, user_message: str | None = None) -> LLMResponse:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        data = self._post(
            url,
            headers={"x-goog-api-key": self.api_key},
            json_body={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": self.render_payload(payload, user_message)}]}],
                "generationConfig": {"maxOutputTokens": self.max_tokens},
            },
        )
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            return LLMResponse(text="", provider=self.name, model=self.model, refused=True)
        return LLMResponse(text=text.strip(), provider=self.name, model=self.model)


class OllamaProvider(_HTTPProvider):
    """Local models. Nothing leaves the machine - the privacy-maximal option."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        super().__init__(timeout)
        self.base_url, self.model = base_url.rstrip("/"), model

    def generate(self, system_prompt: str, payload: dict, user_message: str | None = None) -> LLMResponse:
        data = self._post(
            f"{self.base_url}/api/chat",
            headers={},
            json_body={
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": self.render_payload(payload, user_message)},
                ],
            },
        )
        return LLMResponse(text=data["message"]["content"].strip(), provider=self.name, model=self.model)
