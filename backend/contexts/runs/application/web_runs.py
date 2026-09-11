from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.contexts.constraints.application.cases import INFRASTRUCTURE_KEYS
from backend.contexts.constraints.infrastructure.constraints_io import (
    constraints_from_json,
    constraints_to_json,
)
from backend.contexts.runs.application.run_projection import project_runs
from backend.contexts.runs.domain.errors import RunBusyError, RunRequestError
from backend.contexts.runs.infrastructure.job_store import JobStore
from backend.contexts.runs.infrastructure.worker_process import run_worker
from backend.core.contracts import compensation_policy, water_supply_policy
from backend.shared.json_io import read_json

PARAMETERS = frozenset(INFRASTRUCTURE_KEYS)
MODES: tuple[str, ...] = ("search", "verify")
BUDGETS: tuple[int, ...] = (10, 30, 120)
DEFAULT_MODE = "search"
DEFAULT_BUDGET = 30
RUN_ID_PREFIX = "web-"
RUN_ID_FORMAT = "web-%Y%m%d-%H%M%S-"
RUN_ID_SUFFIX_LENGTH = 8

UNKNOWN_MODE = "Неизвестный вид расчёта."
UNKNOWN_BUDGET = "Выберите 10, 30 или 120 оценок."
UNSUPPORTED_PARAMETER = "В условиях есть неподдерживаемый параметр инфраструктуры."
BUSY = "Расчёт уже выполняется. Дождитесь его окончания."
BAD_RUN_ID = "Некорректный номер прогона."
NO_PLAN_YET = "Сначала найдите план суррогатом."
SEARCH_RUNNING = "Поиск плана суррогатом…"
VERIFY_RUNNING = "Полный расчёт OPM…"
SEARCH_FAILED = (
    "Допустимый план не найден или расчёт завершился ошибкой. "
    "См. причины отклонения ниже."
)
VERIFY_FAILED = (
    "Проверка OPM не завершена. Проверьте доступность Docker и образа OPM."
)
SEARCH_DONE = "Прогноз готов. Для подтверждения запустите OPM."
VERIFY_DONE_SOUND = "OPM завершён. Все проверки пройдены."
VERIFY_DONE_UNSOUND = "OPM завершён: план не прошёл проверку."
EXECUTION_FAILED = (
    "Не удалось завершить расчёт. Подробности сохранены в журнале на сервере."
)


def validated_mode(payload: Mapping[str, Any]) -> str:
    mode = payload.get("mode", DEFAULT_MODE)
    if mode not in MODES:
        raise RunRequestError(UNKNOWN_MODE)
    return str(mode)


def validated_budget(payload: Mapping[str, Any]) -> int:
    budget = payload.get("budget", DEFAULT_BUDGET)
    if type(budget) is not int or budget not in BUDGETS:
        raise RunRequestError(UNKNOWN_BUDGET)
    return budget


def validated_constraints(payload: Mapping[str, Any]):
    constraints = constraints_from_json(payload.get("constraints", {}))
    if set(constraints.infrastructure) - PARAMETERS:
        raise RunRequestError(UNSUPPORTED_PARAMETER)
    water_supply_policy(constraints)
    compensation_policy(constraints)
    return constraints


def validated_run_id(payload: Mapping[str, Any]) -> str:
    run_id = payload.get("run_id", "")
    if (
        not isinstance(run_id, str)
        or not run_id.startswith(RUN_ID_PREFIX)
        or Path(run_id).name != run_id
    ):
        raise RunRequestError(BAD_RUN_ID)
    return run_id


def new_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime(RUN_ID_FORMAT)
    return stamp + uuid.uuid4().hex[:RUN_ID_SUFFIX_LENGTH]


class WebRuns:
    def __init__(self, root: Path):
        self.store = JobStore(root)
        self.lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self.store.root

    def recover_interrupted(self) -> None:
        self.store.recover_interrupted()

    def _write(self, directory: Path, data: Mapping[str, Any]) -> None:
        self.store.write(directory, data)

    def comparison(self, run_id: str) -> Mapping[str, Any] | None:
        directory = self.store.run_directory(run_id)
        if directory is None:
            return None
        return self.store.artifact(directory, "comparison.json")

    def list(self) -> list[dict[str, Any]]:
        return project_runs(self.store)

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        mode = validated_mode(payload)
        budget = validated_budget(payload)
        constraints = validated_constraints(payload) if mode == "search" else None
        if not self.lock.acquire(blocking=False):
            raise RunBusyError(BUSY)
        try:
            if mode == "search":
                run_id = new_run_id()
                directory = self.root / run_id
                directory.mkdir(parents=True)
                write_json_document(
                    directory / "constraints.json", constraints_to_json(constraints)
                )
                data: dict[str, Any] = {
                    "run_id": run_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "budget": budget,
                }
            else:
                run_id = validated_run_id(payload)
                directory = self.root / run_id
                if (
                    not (directory / "manifest.json").is_file()
                    or not (directory / "constraints.json").is_file()
                ):
                    raise RunRequestError(NO_PLAN_YET)
                data = dict(self.store.read(directory))
            data.update(
                status="running",
                mode=mode,
                message=SEARCH_RUNNING if mode == "search" else VERIFY_RUNNING,
            )
            self._write(directory, data)
            threading.Thread(
                target=self._execute,
                args=(directory, data, mode, budget),
                daemon=True,
            ).start()
            return data
        except BaseException:
            self.lock.release()
            raise

    def _execute(
        self, directory: Path, data: dict[str, Any], mode: str, budget: int
    ) -> None:
        try:
            failed = run_worker(directory, mode, budget)
            if failed:
                data.update(
                    status="failed",
                    message=SEARCH_FAILED if mode == "search" else VERIFY_FAILED,
                )
            else:
                data.update(status="completed", message=self._done_message(directory, mode))
        except Exception:
            data.update(status="failed", message=EXECUTION_FAILED)
        finally:
            self._write(directory, data)
            self.lock.release()

    def _done_message(self, directory: Path, mode: str) -> str:
        if mode == "search":
            return SEARCH_DONE
        manifest = read_json(directory / "manifest.json")
        return VERIFY_DONE_SOUND if manifest["sound"] else VERIFY_DONE_UNSOUND


def write_json_document(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )


__all__ = [
    "BUDGETS",
    "BUSY",
    "DEFAULT_BUDGET",
    "DEFAULT_MODE",
    "EXECUTION_FAILED",
    "MODES",
    "PARAMETERS",
    "RUN_ID_FORMAT",
    "RUN_ID_PREFIX",
    "SEARCH_DONE",
    "SEARCH_FAILED",
    "SEARCH_RUNNING",
    "UNKNOWN_BUDGET",
    "UNKNOWN_MODE",
    "UNSUPPORTED_PARAMETER",
    "VERIFY_DONE_SOUND",
    "VERIFY_DONE_UNSOUND",
    "VERIFY_FAILED",
    "VERIFY_RUNNING",
    "WebRuns",
    "new_run_id",
    "validated_budget",
    "validated_constraints",
    "validated_mode",
    "validated_run_id",
]
