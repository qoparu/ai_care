from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.factory import build_provider

_provider_cache: dict[str, LLMProvider] = {}


def require_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Bearer auth. Constant-time compare so the token cannot be timed out of us."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


def get_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    key = f"{settings.llm_provider}:{settings.llm_model}"
    if key not in _provider_cache:
        _provider_cache[key] = build_provider(settings)
    return _provider_cache[key]
