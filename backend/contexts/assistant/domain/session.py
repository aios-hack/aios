from __future__ import annotations

from backend.contexts.assistant.domain.errors import (
    SessionError,
)

import threading
from dataclasses import dataclass, field
from typing import Sequence

from backend.contexts.assistant.domain.ports import SessionRecordStore
from backend.contexts.assistant.domain.session_events import restore_exchanges
from backend.contexts.assistant.domain.console_context import ConsoleContext

HISTORY_LIMIT = 6
MAX_QUESTION_LENGTH = 600
ANSWER_EXCERPT = 300
SUMMARY_LIMIT = 1200


@dataclass(frozen=True, slots=True)
class Exchange:
    question: str
    card_types: tuple[str, ...]
    caption: str
    answer: str = ""

    def as_text(self) -> str:
        cards = ", ".join(self.card_types) if self.card_types else "none"
        lines = [f"Q: {self.question}", f"Cards: {cards}", f"A: {self.caption}"]
        if self.answer:
            lines.append(f"Detail: {self.answer[:ANSWER_EXCERPT]}")
        return "\n".join(lines)


@dataclass
class Session:
    session_id: str
    console: ConsoleContext = field(default_factory=ConsoleContext)
    history: list[Exchange] = field(default_factory=list)
    scene_serial: int = 0
    cancelled: bool = False
    running: bool = False
    summary_text: str = ""
    overflowed: list[Exchange] = field(default_factory=list)
    restored: bool = False

    def remember(self, exchange: Exchange) -> None:
        self.history.append(exchange)
        while len(self.history) > HISTORY_LIMIT:
            self.overflowed.append(self.history.pop(0))

    def next_scene_id(self) -> str:
        self.scene_serial += 1
        return f"s-{self.scene_serial:02d}"

    def questions(self) -> tuple[str, ...]:
        return tuple(
            exchange.question for exchange in (*self.overflowed, *self.history)
        )

    def summary(self) -> str:
        parts: list[str] = []
        if self.summary_text:
            parts.append(f"Summary of older exchanges: {self.summary_text}")
        parts.extend(exchange.as_text() for exchange in self.history)
        return "\n\n".join(parts)

    def pending_summary(self) -> tuple[Exchange, ...]:
        return tuple(self.overflowed)

    def absorb_summary(self, text: str) -> None:
        cleaned = text.strip()[:SUMMARY_LIMIT]
        if cleaned:
            self.summary_text = cleaned
        self.overflowed.clear()


class SessionStore:
    def __init__(
        self,
        history_limit: int = HISTORY_LIMIT,
        disk: SessionRecordStore | None = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._history_limit = history_limit
        self._disk = disk

    @property
    def disk(self) -> SessionRecordStore | None:
        return self._disk

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
        if not session.restored:
            session.restored = True
            self._restore(session)
        return session

    def _restore(self, session: Session) -> None:
        if self._disk is None:
            return
        meta = self._disk.meta(session.session_id)
        if meta is None:
            return
        session.summary_text = meta.summary
        try:
            events = self._disk.events(session.session_id)
        except Exception:
            return
        for row in restore_exchanges(events):
            session.remember(
                Exchange(
                    question=str(row["question"]),
                    card_types=tuple(row["card_types"]),
                    caption=str(row["caption"]),
                    answer=str(row["answer"]),
                )
            )
            session.scene_serial += 1
        session.overflowed.clear()

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
        if self._disk is not None:
            return max(self._disk.count(), len(self._sessions))
        with self._lock:
            return len(self._sessions)

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


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


def summary_request(exchanges: Sequence[Exchange]) -> str:
    lines = [exchange.as_text() for exchange in exchanges]
    return (
        "Сожми эти обмены диалога в короткую справку для памяти: о чём "
        "спрашивали, какие карточки показывали и что было отвечено. Не больше "
        "четырёх фраз, без чисел, которых нет в тексте, без инструментов. "
        "Верни только текст справки.\n\n" + "\n\n".join(lines)
    )
