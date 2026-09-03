from __future__ import annotations

import threading
from dataclasses import dataclass, field

from backend.application.jarvis.tools.context import ConsoleContext

HISTORY_LIMIT = 6
MAX_QUESTION_LENGTH = 600


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Exchange:
    question: str
    card_types: tuple[str, ...]
    caption: str

    def as_text(self) -> str:
        cards = ", ".join(self.card_types) if self.card_types else "none"
        return f"Q: {self.question}\nCards: {cards}\nA: {self.caption}"


@dataclass
class Session:
    session_id: str
    console: ConsoleContext = field(default_factory=ConsoleContext)
    history: list[Exchange] = field(default_factory=list)
    scene_serial: int = 0
    cancelled: bool = False
    running: bool = False

    def remember(self, exchange: Exchange) -> None:
        self.history.append(exchange)
        if len(self.history) > HISTORY_LIMIT:
            del self.history[: len(self.history) - HISTORY_LIMIT]

    def next_scene_id(self) -> str:
        self.scene_serial += 1
        return f"s-{self.scene_serial:02d}"

    def summary(self) -> str:
        return "\n\n".join(exchange.as_text() for exchange in self.history)


class SessionStore:
    def __init__(self, history_limit: int = HISTORY_LIMIT) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._history_limit = history_limit

    def get(self, session_id: str, console: ConsoleContext | None = None) -> Session:
        if not session_id:
            raise SessionError(
                "session_id is empty: Jarvis keeps the console context and the "
                "recent exchanges per session and cannot serve a request without it"
            )
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(session_id=session_id)
                self._sessions[session_id] = session
            if console is not None:
                session.console = console
            return session

    def start(self, session_id: str, console: ConsoleContext) -> Session:
        session = self.get(session_id, console)
        with self._lock:
            if session.running:
                session.cancelled = True
            session.cancelled = False
            session.running = True
        return session

    def finish(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.running = False

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.cancelled = True
            return True

    def is_cancelled(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return bool(session and session.cancelled)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


def check_question(question: str) -> str:
    text = (question or "").strip()
    if not text:
        raise SessionError(
            "the question is empty: nothing to answer, the console offers "
            "suggestion chips instead of sending an empty request"
        )
    if len(text) > MAX_QUESTION_LENGTH:
        raise SessionError(
            f"the question is {len(text)} characters long while the limit is "
            f"{MAX_QUESTION_LENGTH}: shorten it, a long prompt costs latency "
            "without adding precision"
        )
    return text
