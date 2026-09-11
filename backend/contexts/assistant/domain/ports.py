from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class SpeechSynthesis(Protocol):
    @property
    def cache_root(self) -> Path: ...

    @property
    def available(self) -> bool: ...

    def path(self, text: str, voice: str) -> Path: ...


@runtime_checkable
class SpeechRecognition(Protocol):
    def transcribe(
        self, audio: bytes, lang: str | None = "ru", content_type: str | None = None
    ) -> Any: ...


@runtime_checkable
class SessionArchive(Protocol):
    @property
    def root(self) -> Path: ...

    def reload(self) -> None: ...


@runtime_checkable
class ShowcaseReader(Protocol):
    def read(self, *parts: str) -> Any: ...

    def exists(self, *parts: str) -> bool: ...


@runtime_checkable
class DocumentSearch(Protocol):
    def search(self, query: str, limit: int = 5) -> Sequence[Any]: ...


__all__ = [
    "DocumentSearch",
    "SessionArchive",
    "ShowcaseReader",
    "SpeechRecognition",
    "SpeechSynthesis",
]
