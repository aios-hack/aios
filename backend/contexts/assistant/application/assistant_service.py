from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore
from backend.contexts.assistant.infrastructure.docs_index import (
    DocsIndex,
    DocsIndexError,
    load_index,
)
from backend.contexts.assistant.infrastructure.knowledge import Knowledge
from backend.contexts.assistant.application.briefing_cache import BRIEFING_TTL, BriefingCache
from backend.contexts.assistant.application.orchestrator import Event, Orchestrator
from backend.contexts.assistant.domain.session import SessionStore
from backend.contexts.assistant.infrastructure.session_store import SessionDisk, SessionDiskError
from backend.contexts.assistant.infrastructure.stt import SttEngine
from backend.contexts.assistant.infrastructure.system_map import SystemMap, SystemMapError
from backend.contexts.assistant.infrastructure.tts import TtsEngine, default_voice
from backend.contexts.assistant.application.tools.context import ConsoleContext
from backend.contexts.assistant.infrastructure.llm.provider import NoApiKeyError, build_client

DEFAULT_PORT = 8010
DEFAULT_HOST = "0.0.0.0"
DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost:5199",
    "http://127.0.0.1:5199",
)
MAX_BODY_BYTES = 16 * 1024
MAX_AUDIO_BYTES = 2 * 1024 * 1024
AUDIO_ROUTE = "/api/jarvis/transcribe"


class JarvisService:
    def __init__(
        self,
        store: ArtifactStore | None = None,
        knowledge: Knowledge | None = None,
        env: Mapping[str, str] | None = None,
        orchestrator: Orchestrator | None = None,
        docs: DocsIndex | None = None,
        system: SystemMap | None = None,
        disk: SessionDisk | None = None,
        tts: TtsEngine | None = None,
        stt: SttEngine | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store if store is not None else ArtifactStore()
        self._knowledge = knowledge if knowledge is not None else Knowledge()
        self._client_error: str | None = None
        self._orchestrator = orchestrator
        self._clock = clock
        self._docs_error: str | None = None
        self._system_error: str | None = None
        self._docs = docs if docs is not None else self._load_docs()
        self._system = system if system is not None else self._load_system()
        self._disk = disk if disk is not None else self._load_disk()
        self._sessions = (
            orchestrator.sessions
            if orchestrator is not None
            else SessionStore(disk=self._disk)
        )
        self._env = env
        self._tts = tts if tts is not None else TtsEngine()
        self._stt = stt if stt is not None else SttEngine(env)
        self._briefings = BriefingCache(self._clock, BRIEFING_TTL)
        if orchestrator is None:
            self._build()

    def _load_docs(self) -> DocsIndex | None:
        try:
            return load_index()
        except (DocsIndexError, OSError) as error:
            self._docs_error = str(error)
            return None

    def _load_system(self) -> SystemMap | None:
        try:
            return SystemMap()
        except SystemMapError as error:
            self._system_error = str(error)
            return None

    def _load_disk(self) -> SessionDisk | None:
        try:
            return SessionDisk()
        except (SessionDiskError, OSError):
            return None

    def _build(self) -> None:
        try:
            client = build_client(self._env)
        except NoApiKeyError as error:
            self._client_error = str(error)
            return
        self._orchestrator = Orchestrator(
            client=client,
            store=self._store,
            knowledge=self._knowledge,
            sessions=self._sessions,
            docs=self._docs,
            system=self._system,
            disk=self._disk,
            capabilities=self.capabilities,
        )

    @property
    def sessions(self) -> SessionStore:
        return self._sessions

    @property
    def disk(self) -> SessionDisk | None:
        return self._disk

    @property
    def tts(self) -> TtsEngine:
        return self._tts

    @property
    def stt(self) -> SttEngine:
        return self._stt

    @property
    def available(self) -> bool:
        return self._orchestrator is not None

    @property
    def orchestrator(self) -> Orchestrator:
        if self._orchestrator is None:
            raise NoApiKeyError(self._client_error or "no chat client configured")
        return self._orchestrator

    def capabilities(self) -> dict[str, Any]:
        return {
            "tts": self._tts.available,
            "stt": "server" if self._stt.available else "none",
            "docs": self._docs.size() if self._docs is not None else 0,
            "sessions": self._disk.count() if self._disk is not None else 0,
        }

    def health(self) -> tuple[int, dict[str, Any]]:
        body: dict[str, Any] = {
            "data": self._store.scenario().provenance(),
            "scenarios": list(self._store.scenarios()),
            "knowledge": {
                "terms": self._knowledge.term_count,
                "screens": self._knowledge.screen_count,
                "system_nodes": (
                    self._system.node_count if self._system is not None else 0
                ),
            },
            **self.capabilities(),
            "voice": {
                "tts_voice_ru": default_voice("ru"),
                "tts_voice_en": default_voice("en"),
                "stt_model": self._stt.model,
            },
        }
        if self._docs_error is not None:
            body["docs_error"] = self._docs_error
        if self._system_error is not None:
            body["system_error"] = self._system_error
        if self._orchestrator is None:
            body["ok"] = False
            body["error"] = "no-api-key"
            body["message"] = self._client_error or "no chat client configured"
            return 503, body
        body["ok"] = True
        body["provider"] = self._orchestrator.provider
        body["model"] = self._orchestrator.model
        return 200, body

    def session_rows(self) -> list[dict[str, Any]]:
        if self._disk is None:
            return []
        return self._disk.listing()

    def session_events(self, session_id: str) -> list[dict[str, Any]]:
        if self._disk is None:
            raise SessionDiskError(
                "хранилище сессий на диске не поднялось: истории показать "
                "неоткуда"
            )
        return self._disk.events(session_id)

    def remove_session(self, session_id: str) -> bool:
        if self._disk is None:
            return False
        removed = self._disk.remove(session_id)
        self._sessions.forget(session_id)
        return removed

    def briefing(
        self, session_id: str, console: ConsoleContext
    ) -> list[dict[str, Any]]:
        key = (console.scenario, console.step or -1, console.lang)
        cached = self._briefings.get(key)
        if cached is not None:
            return cached
        events = [
            event.as_dict()
            for event in self.orchestrator.briefing(session_id, console)
        ]
        return self._briefings.put(key, events)


def console_context(payload: Mapping[str, Any]) -> ConsoleContext:
    raw = payload.get("context") or {}
    step = raw.get("step")
    return ConsoleContext(
        scenario=str(raw.get("scenario") or "base"),
        step=int(step) if isinstance(step, int) else None,
        date=str(raw["date"]) if raw.get("date") else None,
        selected_well=str(raw["selected_well"]) if raw.get("selected_well") else None,
        workspace=str(raw["workspace"]) if raw.get("workspace") else None,
        view=str(raw["view"]) if raw.get("view") else None,
        lang=str(payload.get("lang") or "ru"),
    )


def query_context(params: Mapping[str, list[str]]) -> ConsoleContext:
    def first(name: str) -> str | None:
        values = params.get(name)
        return values[0] if values else None

    raw_step = first("step")
    step: int | None = None
    if raw_step is not None:
        try:
            step = int(raw_step)
        except ValueError:
            step = None
    return ConsoleContext(
        scenario=first("scenario") or "base",
        step=step,
        date=first("date"),
        selected_well=first("well"),
        workspace=first("workspace"),
        view=first("view"),
        lang=first("lang") or "ru",
    )


__all__ = [
    "AUDIO_ROUTE",
    "BRIEFING_TTL",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEV_ORIGINS",
    "Event",
    "JarvisService",
    "MAX_AUDIO_BYTES",
    "MAX_BODY_BYTES",
    "console_context",
    "query_context",
]
