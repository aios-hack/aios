from __future__ import annotations

import os

from anthropic import Anthropic

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 2000


class LlmClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY не задан: LLM-клиент не работает без ключа, "
                "заглушек в проекте нет. Экспортируйте ключ или передайте api_key."
            )
        self.model = model
        self.max_tokens = max_tokens
        self._client = Anthropic(api_key=key)

    def complete(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("модель отклонила запрос: stop_reason=refusal")
        parts = [block.text for block in response.content if block.type == "text"]
        if not parts:
            raise RuntimeError("модель не вернула текстовых блоков")
        return "".join(parts)
