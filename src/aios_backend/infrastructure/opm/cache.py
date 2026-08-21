"""Кеш прогонов Runner. Контракт §4.5, README.md §6.

Ключ кеша — ровно `deck_hash + canonical_schedule_hash + summary_hash`
(`DeckHashes`, `bridge/runner.py`). Попадание экономит полный прогон Docker/
OPM Flow — задача 5. Кешируются только терминальные исходы настоящего
прогона симулятора: `RunStatus.OK` и `RunStatus.NOT_CONVERGED`, оба
детерминированы входом (деком, расписанием, спецификацией). `FAILED` не
кешируется: он часто инфраструктурный (Docker недоступен, таймаут, дек не
найден), а не свойство самого ключа — навсегда «забивать» ключ таким
результатом было бы неверно.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

from aios_backend.core.contracts import RunResult, RunStatus, Schedule

from .opm_deck import EmittedOpmDeck
from .runner import OpmRunner, OpmRunnerError, deck_hashes

_CACHEABLE_STATUSES = frozenset({RunStatus.OK, RunStatus.NOT_CONVERGED})


def cache_key(deck_hash: str, canonical_schedule_hash: str, summary_hash: str) -> str:
    """Имя файла записи — sha256 тройки хешей, ровно как в контракте §4.5."""

    payload = f"{deck_hash}:{canonical_schedule_hash}:{summary_hash}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class RunCache:
    """Файловый кеш `RunResult`, по одному JSON на ключ.

    Общего изменяемого состояния между записями нет: каждая запись — свой
    файл, запись атомарна (tmp + `os.replace`), поэтому параллельные
    прогоны с разными ключами не мешают друг другу (§4.5).
    """

    def __init__(self, cache_root: Path | str) -> None:
        self.cache_root = Path(cache_root).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _entry_path(self, deck_hash: str, canonical_schedule_hash: str, summary_hash: str) -> Path:
        key = cache_key(deck_hash, canonical_schedule_hash, summary_hash)
        return self.cache_root / f"{key}.json"

    def lookup(
        self, deck_hash: str, canonical_schedule_hash: str, summary_hash: str
    ) -> RunResult | None:
        """`None` — промах или запись стала недействительной.

        Запись недействительна, когда файла нет, JSON не разбирается, или
        любой путь из сохранённых `artifacts` больше не существует на
        диске: сохранённый `RunResult` обязан ссылаться на существующие
        артефакты, а не на удалённую рабочую директорию.
        """

        path = self._entry_path(deck_hash, canonical_schedule_hash, summary_hash)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        try:
            result = RunResult(
                run_id=data["run_id"],
                status=RunStatus(data["status"]),
                deck_hash=data["deck_hash"],
                canonical_schedule_hash=data["canonical_schedule_hash"],
                summary_hash=data["summary_hash"],
                artifacts=tuple(data["artifacts"]),
                wallclock_seconds=data["wallclock_seconds"],
                message=data["message"],
            )
        except (KeyError, ValueError):
            return None

        if not all(Path(artifact).is_file() for artifact in result.artifacts):
            return None
        return result

    def store(self, result: RunResult) -> None:
        """Сохраняет только кешируемые статусы; остальные — no-op."""

        if result.status not in _CACHEABLE_STATUSES:
            return
        path = self._entry_path(
            result.deck_hash, result.canonical_schedule_hash, result.summary_hash
        )
        data = {
            "run_id": result.run_id,
            "status": result.status.value,
            "deck_hash": result.deck_hash,
            "canonical_schedule_hash": result.canonical_schedule_hash,
            "summary_hash": result.summary_hash,
            "artifacts": list(result.artifacts),
            "wallclock_seconds": result.wallclock_seconds,
            "message": result.message,
        }
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)


class CachingOpmRunner:
    """Обёртка над `OpmRunner`: тот же публичный API, плюс кеш по ключу §4.5.

    Не правит `OpmRunner` — используется как замена там, где нужен кеш, а
    исходный класс остаётся стабильным чужим интерфейсом (§4.4, README §6).
    """

    def __init__(self, runner: OpmRunner, cache: RunCache) -> None:
        self._runner = runner
        self._cache = cache

    def run(
        self,
        deck: EmittedOpmDeck,
        schedule: Schedule,
        *,
        run_id: str | None = None,
        flow_args: Sequence[str] | None = None,
    ) -> RunResult:
        """Тот же контракт, что `OpmRunner.run`, плюс кеш-попадание."""

        try:
            hashes = deck_hashes(deck, schedule)
        except (OpmRunnerError, OSError, ValueError):
            # Ключ не собран — тот же случай, что и в OpmRunner.run: нечего
            # кешировать, кешу тоже нечего искать, делегируем как есть.
            return self._runner.run(deck, schedule, run_id=run_id, flow_args=flow_args)

        cached = self._cache.lookup(
            hashes.deck_hash, hashes.canonical_schedule_hash, hashes.summary_hash
        )
        if cached is not None:
            return cached

        result = self._runner.run(deck, schedule, run_id=run_id, flow_args=flow_args)
        self._cache.store(result)
        return result

    def run_data_file(
        self,
        data_file: Path | str,
        *,
        deck_hash: str,
        canonical_schedule_hash: str,
        summary_hash: str,
        run_id: str | None = None,
        flow_args: Sequence[str] | None = None,
    ) -> RunResult:
        """Тот же контракт, что `OpmRunner.run_data_file`, плюс кеш-попадание."""

        cached = self._cache.lookup(deck_hash, canonical_schedule_hash, summary_hash)
        if cached is not None:
            return cached

        result = self._runner.run_data_file(
            data_file,
            deck_hash=deck_hash,
            canonical_schedule_hash=canonical_schedule_hash,
            summary_hash=summary_hash,
            run_id=run_id,
            flow_args=flow_args,
        )
        self._cache.store(result)
        return result
