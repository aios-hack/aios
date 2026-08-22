from __future__ import annotations

import pytest

# `llm/client.py` импортирует `anthropic` на уровне модуля, а он не объявлен
# в `pyproject.toml` (README §3): в нативной установке его ставят отдельно.
# Без этой строки отсутствие пакета — не skip, а ошибка сбора, которая рушит
# весь прогон `pytest`, включая тесты, к LLM отношения не имеющие.
pytest.importorskip(
    "anthropic",
    reason="слой llm/ требует пакет anthropic; поставьте его отдельно (README §3)",
)

from backend.infrastructure.llm.client import DEFAULT_MODEL, LlmClient  # noqa: E402


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
