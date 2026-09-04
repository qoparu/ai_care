"""Provider-agnostic LLM interface.

The application never imports a vendor SDK outside app/llm/providers.py.
Swapping providers is a config change, not a code change.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str | None = None
    refused: bool = False


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, system_prompt: str, payload: dict, user_message: str | None = None) -> LLMResponse:
        """Turn a structured, already-validated feature payload into prose.

        `payload` MUST contain only derived features - never raw sensor streams,
        never identifiers. See app/llm/prompts.py for what is sent.
        """

    @staticmethod
    def render_payload(payload: dict, user_message: str | None) -> str:
        parts = ["<data>", json.dumps(payload, ensure_ascii=False, indent=2, default=str), "</data>"]
        if user_message:
            parts.append(f"\n<question>{user_message}</question>")
        return "\n".join(parts)
