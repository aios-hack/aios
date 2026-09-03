from __future__ import annotations

from typing import Any, Mapping

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.knowledge import Knowledge
from backend.application.jarvis.orchestrator import Orchestrator
from backend.application.jarvis.session import SessionStore
from backend.application.jarvis.tools.context import ConsoleContext
from backend.infrastructure.llm.provider import NoApiKeyError, build_client

DEFAULT_PORT = 8010
DEFAULT_HOST = "0.0.0.0"
DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost:5199",
    "http://127.0.0.1:5199",
)
MAX_BODY_BYTES = 16 * 1024


class JarvisService:
    def __init__(
        self,
        store: ArtifactStore | None = None,
        knowledge: Knowledge | None = None,
        env: Mapping[str, str] | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        self._store = store if store is not None else ArtifactStore()
        self._knowledge = knowledge if knowledge is not None else Knowledge()
        self._client_error: str | None = None
        self._orchestrator = orchestrator
        self._sessions = (
            orchestrator.sessions if orchestrator is not None else SessionStore()
        )
        self._env = env
        if orchestrator is None:
            self._build()

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
        )

    @property
    def sessions(self) -> SessionStore:
        return self._sessions

    @property
    def available(self) -> bool:
        return self._orchestrator is not None

    @property
    def orchestrator(self) -> Orchestrator:
        if self._orchestrator is None:
            raise NoApiKeyError(self._client_error or "no chat client configured")
        return self._orchestrator

    def health(self) -> tuple[int, dict[str, Any]]:
        body: dict[str, Any] = {
            "data": self._store.scenario().provenance(),
            "scenarios": list(self._store.scenarios()),
            "knowledge": {
                "terms": self._knowledge.term_count,
                "screens": self._knowledge.screen_count,
            },
        }
        if self._orchestrator is None:
            body["ok"] = False
            body["error"] = "no-api-key"
            body["message"] = self._client_error or "no chat client configured"
            return 503, body
        body["ok"] = True
        body["provider"] = self._orchestrator.provider
        body["model"] = self._orchestrator.model
        return 200, body


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


