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
class SessionMeta(Protocol):
    @property
    def summary(self) -> str: ...


@runtime_checkable
class SessionRecordStore(Protocol):
    def meta(self, session_id: str) -> SessionMeta | None: ...

    def events(self, session_id: str) -> list[dict[str, Any]]: ...


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
    "SessionMeta",
    "SessionRecordStore",
    "ShowcaseReader",
    "SpeechRecognition",
    "SpeechSynthesis",
]
