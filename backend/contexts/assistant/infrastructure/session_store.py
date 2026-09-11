from __future__ import annotations

from backend.contexts.assistant.domain.errors import (
    SessionDiskError,
)

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from backend.shared.settings import Settings
from backend.shared.paths import repository_root

SESSIONS_ENV_VAR = "AIOS_JARVIS_SESSIONS"
OUT_ENV_VAR = "AIOS_OUT_DIR"
EVENTS_FILE = "events.jsonl"
META_FILE = "meta.json"
ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_EVENTS = 4000


def now() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _repository_root() -> Path:
    return repository_root(Path.cwd())


def default_sessions_root(settings: Settings | None = None) -> Path:
    resolved = Settings.from_env() if settings is None else settings
    if resolved.jarvis_sessions is not None:
        return resolved.jarvis_sessions
    base = resolved.out_root if resolved.raw.get(OUT_ENV_VAR) else _repository_root() / "out"
    return base / "jarvis" / "sessions"


def check_id(session_id: str) -> str:
    text = str(session_id or "").strip()
    if not ID_PATTERN.match(text):
        raise SessionDiskError(
            f"идентификатор сессии {session_id!r} не годится для имени каталога: "
            "допустимы латинские буквы, цифры, точка, дефис и подчёркивание, "
            "не длиннее 80 символов"
        )
    return text


@dataclass
class Meta:
    session_id: str
    started: str
    last: str
    scenes: int = 0
    summary: str = ""
    first_question: str = ""
    lang: str = "ru"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.session_id,
            "started": self.started,
            "last": self.last,
            "scenes": self.scenes,
            "summary": self.summary,
            "first_question": self.first_question,
            "lang": self.lang,
        }

    def as_row(self) -> dict[str, Any]:
        return {
            "id": self.session_id,
            "started": self.started,
            "last": self.last,
            "scenes": self.scenes,
            "first_question": self.first_question,
        }


def _read_meta(path: Path) -> Meta | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(loaded, dict):
        return None
    identifier = str(loaded.get("id") or path.parent.name)
    stamp = str(loaded.get("started") or now())
    return Meta(
        session_id=identifier,
        started=stamp,
        last=str(loaded.get("last") or stamp),
        scenes=int(loaded.get("scenes") or 0),
        summary=str(loaded.get("summary") or ""),
        first_question=str(loaded.get("first_question") or ""),
        lang=str(loaded.get("lang") or "ru"),
    )


class SessionDisk:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else default_sessions_root()
        self._lock = threading.Lock()
        self._meta: dict[str, Meta] = {}
        self.reload()

    @property
    def root(self) -> Path:
        return self._root

    def reload(self) -> None:
        collected: dict[str, Meta] = {}
        if self._root.is_dir():
            for entry in sorted(self._root.iterdir()):
                if not entry.is_dir():
                    continue
                path = entry / META_FILE
                if not path.is_file():
                    continue
                meta = _read_meta(path)
                if meta is not None:
                    collected[meta.session_id] = meta
        with self._lock:
            self._meta = collected

    def count(self) -> int:
        with self._lock:
            return len(self._meta)

    def listing(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [meta.as_row() for meta in self._meta.values()]
        rows.sort(key=lambda row: str(row["last"]), reverse=True)
        return rows

    def meta(self, session_id: str) -> Meta | None:
        with self._lock:
            return self._meta.get(session_id)

    def directory(self, session_id: str) -> Path:
        return self._root / check_id(session_id)

    def _ensure(self, session_id: str, lang: str) -> Meta:
        with self._lock:
            found = self._meta.get(session_id)
            if found is not None:
                return found
            stamp = now()
            created = Meta(
                session_id=session_id, started=stamp, last=stamp, lang=lang
            )
            self._meta[session_id] = created
            return created

    def _write_meta(self, meta: Meta) -> None:
        directory = self.directory(meta.session_id)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / META_FILE).write_text(
                json.dumps(meta.as_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as error:
            raise SessionDiskError(
                f"метаданные сессии {meta.session_id} не записываются в "
                f"{directory}: {error}"
            ) from error

    def append(self, session_id: str, event: Mapping[str, Any], lang: str = "ru") -> None:
        identifier = check_id(session_id)
        meta = self._ensure(identifier, lang)
        directory = self.directory(identifier)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / EVENTS_FILE).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(event), ensure_ascii=False) + "\n")
        except OSError:
            return
        meta.last = now()
        if event.get("type") == "ask":
            meta.scenes += 1
            if not meta.first_question:
                meta.first_question = str(event.get("question") or "")[:200]
        self._write_meta(meta)

    def set_summary(self, session_id: str, summary: str) -> None:
        meta = self.meta(check_id(session_id))
        if meta is None:
            return
        meta.summary = summary
        meta.last = now()
        self._write_meta(meta)

    def events(self, session_id: str) -> list[dict[str, Any]]:
        directory = self.directory(session_id)
        path = directory / EVENTS_FILE
        if not path.is_file():
            raise SessionDiskError(
                f"сессии {session_id} нет на диске: файла {path} не "
                "существует, историю показать не из чего"
            )
        collected: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        loaded = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(loaded, dict):
                        collected.append(loaded)
                    if len(collected) >= MAX_EVENTS:
                        break
        except OSError as error:
            raise SessionDiskError(
                f"события сессии {session_id} не читаются из {path}: {error}"
            ) from error
        return collected

    def remove(self, session_id: str) -> bool:
        identifier = check_id(session_id)
        directory = self.directory(identifier)
        with self._lock:
            existed = self._meta.pop(identifier, None) is not None
        if not directory.is_dir():
            return existed
        for path in sorted(directory.iterdir(), reverse=True):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
        return True

    def exchanges(self, session_id: str) -> Iterator[Mapping[str, Any]]:
        try:
            events = self.events(session_id)
        except SessionDiskError:
            return iter(())
        return iter(events)


def restore_exchanges(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in events:
        kind = event.get("type")
        if kind == "ask":
            if current is not None:
                collected.append(current)
            current = {
                "question": str(event.get("question") or ""),
                "card_types": [],
                "caption": "",
                "answer": "",
            }
        elif current is None:
            continue
        elif kind == "card":
            card = event.get("card") or {}
            if isinstance(card, Mapping):
                current["card_types"].append(str(card.get("type") or ""))
        elif kind == "caption":
            current["caption"] = str(event.get("text") or "")
        elif kind == "answer":
            current["answer"] = str(event.get("text") or "")
    if current is not None:
        collected.append(current)
    return collected


__all__ = [
    "EVENTS_FILE",
    "META_FILE",
    "Meta",
    "SESSIONS_ENV_VAR",
    "SessionDisk",
    "SessionDiskError",
    "check_id",
    "default_sessions_root",
    "now",
    "restore_exchanges",
]
