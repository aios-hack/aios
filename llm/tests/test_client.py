from __future__ import annotations

import pytest

from llm.client import DEFAULT_MODEL, LlmClient


def test_client_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        LlmClient()


def test_client_empty_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        LlmClient()


def test_client_builds_with_explicit_key() -> None:
    client = LlmClient(api_key="sk-test-not-a-real-key")
    assert client.model == DEFAULT_MODEL
    assert client.max_tokens > 0
