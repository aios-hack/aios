from __future__ import annotations

import os
from typing import Mapping

from backend.infrastructure.llm.anthropic_chat import AnthropicChatClient
from backend.infrastructure.llm.chat import ChatClient
from backend.infrastructure.llm.openrouter import DEFAULT_MODEL, OpenRouterClient

PROVIDER_ENV_VAR = "JARVIS_PROVIDER"
MODEL_ENV_VAR = "JARVIS_MODEL"
MAX_TOKENS_ENV_VAR = "JARVIS_MAX_TOKENS"
OPENROUTER_KEY_VAR = "OPENROUTER_API_KEY"
ANTHROPIC_KEY_VAR = "ANTHROPIC_API_KEY"
ANTHROPIC_FALLBACK_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 1200


class NoApiKeyError(RuntimeError):
    pass


def _max_tokens(env: Mapping[str, str]) -> int:
    raw = env.get(MAX_TOKENS_ENV_VAR)
    if not raw:
        return DEFAULT_MAX_TOKENS
    try:
        return int(raw)
    except ValueError as error:
        raise RuntimeError(
            f"{MAX_TOKENS_ENV_VAR}={raw!r} is not a number: the answer length "
            "limit must be an integer"
        ) from error


def build_client(env: Mapping[str, str] | None = None) -> ChatClient:
    values = env if env is not None else os.environ
    preferred = (values.get(PROVIDER_ENV_VAR) or "openrouter").strip().lower()
    if preferred not in ("openrouter", "anthropic"):
        raise RuntimeError(
            f"{PROVIDER_ENV_VAR}={preferred!r} is not supported: the allowed "
            "values are openrouter and anthropic"
        )
    openrouter_key = values.get(OPENROUTER_KEY_VAR) or ""
    anthropic_key = values.get(ANTHROPIC_KEY_VAR) or ""
    max_tokens = _max_tokens(values)
    order = (
        ("openrouter", "anthropic")
        if preferred == "openrouter"
        else ("anthropic", "openrouter")
    )
    for name in order:
        if name == "openrouter" and openrouter_key:
            return OpenRouterClient(
                api_key=openrouter_key,
                model=values.get(MODEL_ENV_VAR) or DEFAULT_MODEL,
                max_tokens=max_tokens,
            )
        if name == "anthropic" and anthropic_key:
            model = values.get(MODEL_ENV_VAR) or ANTHROPIC_FALLBACK_MODEL
            if "/" in model:
                model = model.split("/", 1)[1]
            return AnthropicChatClient(
                api_key=anthropic_key, model=model, max_tokens=max_tokens
            )
    raise NoApiKeyError(
        f"neither {OPENROUTER_KEY_VAR} nor {ANTHROPIC_KEY_VAR} is set: Jarvis "
        "cannot reach a model. The service still starts and answers 503, and "
        "the frontend falls back to the fixture demo mode"
    )
