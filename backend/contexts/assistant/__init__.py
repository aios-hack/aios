from __future__ import annotations

from backend.contexts.assistant.application.assistant_service import JarvisService
from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore
from backend.contexts.assistant.infrastructure.docs_index import (
    DocsIndex,
    DocsIndexError,
    load_index,
)
from backend.contexts.assistant.infrastructure.knowledge import KnowledgeStore
from backend.contexts.assistant.infrastructure.session_store import SessionDisk
from backend.contexts.assistant.infrastructure.stt import SttEngine
from backend.contexts.assistant.infrastructure.system_map import SystemMap, SystemMapError
from backend.contexts.assistant.infrastructure.tts import TtsEngine
from backend.shared.settings import Settings


def build_assistant(settings: Settings | None = None) -> JarvisService:
    chosen = settings if settings is not None else Settings.from_env()
    store = ArtifactStore(chosen.jarvis_runs or chosen.data_root)
    knowledge = KnowledgeStore(chosen.jarvis_knowledge)
    docs = _docs_index(chosen)
    system = _system_map(chosen)
    disk = SessionDisk(chosen.jarvis_sessions)
    tts = TtsEngine(chosen.jarvis_tts_cache)
    stt = SttEngine(chosen.raw)
    return JarvisService(
        store=store,
        knowledge=knowledge,
        env=chosen.raw,
        docs=docs,
        system=system,
        disk=disk,
        tts=tts,
        stt=stt,
    )


def _docs_index(settings: Settings) -> DocsIndex | None:
    try:
        return load_index(knowledge_root=settings.jarvis_knowledge)
    except (DocsIndexError, OSError):
        return None


def _system_map(settings: Settings) -> SystemMap | None:
    try:
        return SystemMap(settings.jarvis_system)
    except (SystemMapError, OSError):
        return None


__all__ = ["JarvisService", "build_assistant"]
