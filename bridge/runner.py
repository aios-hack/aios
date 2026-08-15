"""Запуск OPM Flow над эмитированным деком. Контракт §4.4, README.md §6.

Падение прогона — данные, а не исключение: наружу всегда выходит `RunResult`
со статусом, ни одна ошибка запуска не поднимается вызывающему. Кеша здесь
нет (задача 5), разбора отклика тоже (задача 6) — только запуск и статус.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from contracts import (
    RunResult,
    RunStatus,
    Schedule,
    SummarySpec,
    canonical_bytes,
    hash_schedule,
)

from .opm_deck import EmittedOpmDeck, bundle_hash


DEFAULT_OPM_IMAGE = "openporousmedia/opmreleases:latest"
OPM_IMAGE_ENV = "OPM_FLOW_IMAGE"

# Та же строгость разбора, на которой Model_Z прошла приёмку задачи 2.
DEFAULT_FLOW_ARGS: tuple[str, ...] = ("--parsing-strictness=low",)

_CONTAINER_PREFIX = "opm-run-"
_LOG_NAME = "flow.log"
_COMMAND_NAME = "command.txt"
_OUTPUT_DIR = "output"

# Flow 2026.04 завершается кодом 0, даже когда решатель не сошёлся ни на одном
# шаге: он принимает несошедшийся шаг, если тот уже равен минимальному, и
# рапортует «Wasted: 100%» только в статистике. Поэтому код возврата
# несходимость не ловит, и единственный признак — текст лога.
_NOT_CONVERGED_MARKERS: tuple[str, ...] = (
    # покрывает и «...but timestep X is smaller or equal to Y», и
    # «...after cutting timestep N times» — оба означают принятый или
    # брошенный несошедшийся шаг
    "Solver failed to converge",
    # текст NumericalProblem, с которым Flow снимает прогон
    "Solver convergence failure",
)

# Восстановимые сообщения того же семейства, которые встречаются и в успешном
# прогоне: линейный решатель промахнулся, Flow срезал шаг и сошёлся дальше.
# В маркеры не входят намеренно — иначе нормальный прогон получит
# NOT_CONVERGED.
_RECOVERABLE_MARKERS: tuple[str, ...] = (
    "Linear solver convergence failure",
    "Convergence failure for linear solver",
    "Unconverged local solution with well convergence failures",
)


class OpmRunnerError(ValueError):
    """Вход нельзя превратить в однозначный ключ прогона."""


@dataclass(frozen=True, slots=True)
class DeckHashes:
    """Три хеша `RunResult`, вычисленные из дека, расписания и спецификации."""

    deck_hash: str
    canonical_schedule_hash: str
    summary_hash: str


def summary_spec_hash(spec: SummarySpec) -> str:
    """Хеш `SummarySpec` целиком — все три кортежа как один объект (§6)."""

    return hashlib.sha256(canonical_bytes(spec)).hexdigest()


def static_deck_hash(deck: EmittedOpmDeck) -> str:
    """Хеш только статики дека: входы без управляющего слоя и без SUMMARY.

    `RunResult.deck_hash` по контракту — статическая часть, поэтому
    `Model_Z_sch.inc` и `Model_Z_summary.inc` из хеша исключены: их вклад
    несут `canonical_schedule_hash` и `summary_hash`. Хеш байтов дека
    целиком — это `EmittedOpmDeck.content_hash_opm`, другая величина (§6a).
    """

    variable = {deck.schedule_file.resolve(), deck.summary_file.resolve()}
    static = [path for path in deck.input_files if path.resolve() not in variable]
    if len(static) != len(deck.input_files) - len(variable):
        raise OpmRunnerError(
            "в input_files дека нет ровно двух переменных файлов "
            f"({deck.schedule_file.name}, {deck.summary_file.name})"
        )
    return bundle_hash(static, deck.data_file.parent)


def deck_hashes(deck: EmittedOpmDeck, schedule: Schedule) -> DeckHashes:
    """Собирает три хеша прогона из того, что реально пошло в симулятор."""

    return DeckHashes(
        deck_hash=static_deck_hash(deck),
        canonical_schedule_hash=hash_schedule(schedule),
        summary_hash=summary_spec_hash(deck.summary_plan.spec),
    )


def _tail(path: Path, *, max_lines: int = 15, max_chars: int = 2000) -> str:
    """Хвост лога для диагностики — без выгрузки всего файла в сообщение."""

    try:
        lines = [
            line.rstrip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except OSError as error:
        return f"<лог не прочитан: {error}>"
    text = "\n".join(lines[-max_lines:])
    return text[-max_chars:]


def _first_marker(path: Path, markers: Sequence[str]) -> str | None:
    """Первый маркер несходимости в логе, построчно — лог бывает большим."""

    try:
        with path.open("r", encoding="utf-8", errors="replace") as log:
            for line in log:
                for marker in markers:
                    if marker in line:
                        return marker
    except OSError:
        return None
    return None


class OpmRunner:
    """Запускает Flow в Docker, каждый прогон — в своей рабочей директории.

    Общего изменяемого состояния нет: каталог дека монтируется только на
    чтение, всё, что пишет симулятор, попадает в `<work_root>/<run_id>/`.
    Два прогона одного и того же дека не видят файлов друг друга.
    """

    def __init__(
        self,
        work_root: Path | str,
        *,
        image: str | None = None,
        docker_binary: str = "docker",
        flow_args: Sequence[str] = DEFAULT_FLOW_ARGS,
        timeout_seconds: float | None = None,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.image = image or os.environ.get(OPM_IMAGE_ENV, DEFAULT_OPM_IMAGE)
        self.docker_binary = docker_binary
        self.flow_args = tuple(flow_args)
        self.timeout_seconds = timeout_seconds

    # --- публичный вход -------------------------------------------------

    def run(
        self,
        deck: EmittedOpmDeck,
        schedule: Schedule,
        *,
        run_id: str | None = None,
        flow_args: Sequence[str] | None = None,
    ) -> RunResult:
        """Прогнать эмитированный дек. Ошибка ключа — тоже `RunResult`."""

        run_id = run_id or self.new_run_id()
        started = time.perf_counter()
        try:
            hashes = deck_hashes(deck, schedule)
        except (OpmRunnerError, OSError, ValueError) as error:
            return RunResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                deck_hash="",
                canonical_schedule_hash="",
                summary_hash="",
                artifacts=(),
                wallclock_seconds=time.perf_counter() - started,
                message=f"ключ прогона не собран: {error}",
            )
        return self.run_data_file(
            deck.data_file,
            deck_hash=hashes.deck_hash,
            canonical_schedule_hash=hashes.canonical_schedule_hash,
            summary_hash=hashes.summary_hash,
            run_id=run_id,
            flow_args=flow_args,
        )

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
        """Прогнать любой готовый `.DATA`. Наружу не бросает ничего."""

        run_id = run_id or self.new_run_id()
        started = time.perf_counter()

        def result(status: RunStatus, message: str, workdir: Path | None) -> RunResult:
            return RunResult(
                run_id=run_id,
                status=status,
                deck_hash=deck_hash,
                canonical_schedule_hash=canonical_schedule_hash,
                summary_hash=summary_hash,
                artifacts=_collect_artifacts(workdir),
                wallclock_seconds=time.perf_counter() - started,
                message=message,
            )

        data_file = Path(data_file).resolve()
        try:
            workdir = self._make_workdir(run_id)
        except OSError as error:
            return result(RunStatus.FAILED, f"рабочая директория не создана: {error}", None)

        if not data_file.is_file():
            return result(RunStatus.FAILED, f"дек не найден: {data_file}", workdir)

        output_dir = workdir / _OUTPUT_DIR
        log_file = workdir / _LOG_NAME
        container = _CONTAINER_PREFIX + run_id
        command = self._command(data_file, output_dir, container, flow_args)
        try:
            output_dir.mkdir()
            (workdir / _COMMAND_NAME).write_text(shlex.join(command) + "\n", encoding="utf-8")
        except OSError as error:
            return result(RunStatus.FAILED, f"рабочая директория не готова: {error}", workdir)

        try:
            with log_file.open("wb") as log:
                completed = subprocess.run(
                    command,
                    check=False,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=self.timeout_seconds,
                )
        except subprocess.TimeoutExpired:
            self._force_remove_container(container)
            return result(
                RunStatus.FAILED,
                f"flow не уложился в {self.timeout_seconds} с, контейнер {container} снят; "
                f"лог: {log_file}\n{_tail(log_file)}",
                workdir,
            )
        except OSError as error:
            # docker не найден или недоступен — это отказ запуска, не отказ
            # симулятора, но наружу всё равно уходит статусом.
            return result(
                RunStatus.FAILED,
                f"не удалось запустить {self.docker_binary!r}: {error}",
                workdir,
            )

        returncode = completed.returncode
        marker = _first_marker(log_file, _NOT_CONVERGED_MARKERS)
        if marker is not None:
            return result(
                RunStatus.NOT_CONVERGED,
                f"OPM не сошёлся: «{marker}» в логе, код возврата {returncode}; "
                f"лог: {log_file}\n{_tail(log_file)}",
                workdir,
            )
        if returncode != 0:
            return result(
                RunStatus.FAILED,
                f"flow завершился кодом {returncode}; лог: {log_file}\n{_tail(log_file)}",
                workdir,
            )
        return result(
            RunStatus.OK,
            f"flow завершился кодом 0, образ {self.image}; лог: {log_file}",
            workdir,
        )

    # --- внутреннее -----------------------------------------------------

    @staticmethod
    def new_run_id() -> str:
        """Уникален для каждого прогона, включая повтор того же дека."""

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"{stamp}-{uuid.uuid4().hex[:12]}"

    def _make_workdir(self, run_id: str) -> Path:
        workdir = self.work_root / run_id
        workdir.mkdir(parents=True, exist_ok=False)
        return workdir

    def _command(
        self,
        data_file: Path,
        output_dir: Path,
        container: str,
        flow_args: Sequence[str] | None,
    ) -> list[str]:
        args = self.flow_args if flow_args is None else tuple(flow_args)
        return [
            self.docker_binary,
            "run",
            "--rm",
            "--name",
            container,
            "-v",
            f"{data_file.parent}:/deck:ro",
            "-v",
            f"{output_dir}:/out",
            self.image,
            "flow",
            f"/deck/{data_file.name}",
            "--output-dir=/out",
            *args,
        ]

    def _force_remove_container(self, container: str) -> None:
        """Снятый по таймауту клиент не убивает контейнер — снимаем явно."""

        try:
            subprocess.run(
                [self.docker_binary, "rm", "-f", container],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _collect_artifacts(workdir: Path | None) -> tuple[str, ...]:
    """Пути к тому, что действительно лежит на диске после прогона."""

    if workdir is None:
        return ()
    try:
        return tuple(
            str(path) for path in sorted(workdir.rglob("*")) if path.is_file()
        )
    except OSError:
        return ()
