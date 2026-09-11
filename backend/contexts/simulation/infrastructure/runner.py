from __future__ import annotations

from backend.contexts.simulation.domain.errors import (
    OpmRunnerError,
)

import hashlib
import json
import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from backend.core.contracts import (
    RunResult,
    RunStatus,
    Schedule,
    SummarySpec,
    canonical_bytes,
    hash_schedule,
)
from backend.shared.paths import out_root
from backend.contexts.runs.infrastructure.provenance import DEFAULT_OPM_IMAGE, OPM_IMAGE_ENV

from backend.contexts.reservoir.infrastructure.opm_deck import EmittedOpmDeck, bundle_hash
from backend.contexts.simulation.infrastructure.preflight import (
    DockerPreflightError,
    ImageReference,
    PreflightReport,
    ensure_docker_ready,
    resolve_image_reference,
)

__all__ = [
    "BUDGET_CASE_ENV",
    "BUDGET_INITIATOR_ENV",
    "BUDGET_JOURNAL_ENV",
    "BUDGET_JOURNAL_NAME",
    "DEFAULT_FLOW_ARGS",
    "DEFAULT_OPM_IMAGE",
    "DeckHashes",
    "DockerPreflightError",
    "ImageReference",
    "OPM_IMAGE_ENV",
    "OPM_USER_ENV",
    "OpmRunner",
    "OpmRunnerError",
    "PreflightReport",
    "budget_journal_path",
    "deck_hashes",
    "default_run_as_user",
    "mount_path",
    "record_budget_entry",
    "resolve_case",
    "resolve_initiator",
    "static_deck_hash",
    "summary_spec_hash",
]

_EXTENDED_LENGTH_PREFIX = "\\\\?\\"
_EXTENDED_LENGTH_UNC_PREFIX = "\\\\?\\UNC\\"


def mount_path(path: Path | str) -> str:

    text = str(path)
    if text.startswith(_EXTENDED_LENGTH_UNC_PREFIX):
        return "\\\\" + text[len(_EXTENDED_LENGTH_UNC_PREFIX):]
    if text.startswith(_EXTENDED_LENGTH_PREFIX):
        return text[len(_EXTENDED_LENGTH_PREFIX):]
    return text


OPM_USER_ENV = "OPM_RUN_AS_USER"

DEFAULT_FLOW_ARGS: tuple[str, ...] = ("--parsing-strictness=low",)

_UNSET: str = "<unset>"


def default_run_as_user() -> str | None:
    override = os.environ.get(OPM_USER_ENV)
    if override is not None:
        return override.strip() or None
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return None
    return f"{getuid()}:{getgid()}"


_CONTAINER_PREFIX = "opm-run-"
_LOG_NAME = "flow.log"
_COMMAND_NAME = "command.txt"
_OUTPUT_DIR = "output"

_NOT_CONVERGED_MARKERS: tuple[str, ...] = (
    "Solver failed to converge",
)

_ITERATION_LIMIT_MARKER = "Solver convergence failure"
_CHOP_RECOVERY_MARKER = "Timestep chopped to"
_CHOP_RECOVERY_LOOKAHEAD_LINES = 5

_RECOVERABLE_MARKERS: tuple[str, ...] = (
    "Linear solver convergence failure",
    "Convergence failure for linear solver",
    "Unconverged local solution with well convergence failures",
)


BUDGET_JOURNAL_NAME = "opm-budget.jsonl"
BUDGET_JOURNAL_ENV = "AIOS_OPM_BUDGET_JOURNAL"
BUDGET_INITIATOR_ENV = "AIOS_RUN_INITIATOR"
BUDGET_CASE_ENV = "AIOS_CONSTRAINTS_PATH"

_PYTEST_ENV = "PYTEST_CURRENT_TEST"
_INITIATOR_TEST = "test"
_INITIATOR_UNKNOWN = "unknown"
_KNOWN_INITIATORS: frozenset[str] = frozenset({"cli", "ui", _INITIATOR_TEST})


def budget_journal_path() -> Path:
    override = os.environ.get(BUDGET_JOURNAL_ENV)
    if override is not None and override.strip():
        return Path(override).expanduser()
    return out_root() / BUDGET_JOURNAL_NAME


def resolve_initiator() -> str:
    declared = os.environ.get(BUDGET_INITIATOR_ENV, "").strip().lower()
    if declared in _KNOWN_INITIATORS:
        return declared
    if os.environ.get(_PYTEST_ENV):
        return _INITIATOR_TEST
    if declared:
        return declared
    return _INITIATOR_UNKNOWN


def resolve_case() -> str | None:
    case = os.environ.get(BUDGET_CASE_ENV, "").strip()
    if not case:
        return None
    return Path(case).name


def record_budget_entry(result: RunResult, *, journal: Path | None = None) -> None:
    wallclock = result.wallclock_seconds
    if not isinstance(wallclock, (int, float)) or isinstance(wallclock, bool):
        wallclock = None
    elif wallclock != wallclock or wallclock in (float("inf"), float("-inf")) or wallclock < 0.0:
        wallclock = None
    else:
        wallclock = float(wallclock)
    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": result.run_id,
        "canonical_schedule_hash": result.canonical_schedule_hash,
        "case": resolve_case(),
        "wallclock_seconds": wallclock,
        "status": result.status.value,
        "initiator": resolve_initiator(),
    }
    path = journal if journal is not None else budget_journal_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as journal_file:
            journal_file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return


@dataclass(frozen=True, slots=True)
class DeckHashes:

    deck_hash: str
    canonical_schedule_hash: str
    summary_hash: str


def summary_spec_hash(spec: SummarySpec) -> str:

    return hashlib.sha256(canonical_bytes(spec)).hexdigest()


def static_deck_hash(deck: EmittedOpmDeck) -> str:

    variable = {deck.schedule_file.resolve(), deck.summary_file.resolve()}
    static = [path for path in deck.input_files if path.resolve() not in variable]
    if len(static) != len(deck.input_files) - len(variable):
        raise OpmRunnerError(
            "в input_files дека нет ровно двух переменных файлов "
            f"({deck.schedule_file.name}, {deck.summary_file.name})"
        )
    return bundle_hash(static, deck.data_file.parent)


def deck_hashes(deck: EmittedOpmDeck, schedule: Schedule) -> DeckHashes:

    return DeckHashes(
        deck_hash=static_deck_hash(deck),
        canonical_schedule_hash=hash_schedule(schedule),
        summary_hash=summary_spec_hash(deck.summary_plan.spec),
    )


def _tail(path: Path, *, max_lines: int = 15, max_chars: int = 2000) -> str:

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


def _unrecovered_iteration_limit_failure(path: Path) -> bool:

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for index, line in enumerate(lines):
        if _ITERATION_LIMIT_MARKER not in line:
            continue
        window = lines[index : index + 1 + _CHOP_RECOVERY_LOOKAHEAD_LINES]
        if not any(_CHOP_RECOVERY_MARKER in window_line for window_line in window):
            return True
    return False


def _first_marker(path: Path, markers: Sequence[str]) -> str | None:

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

    def __init__(
        self,
        work_root: Path | str,
        *,
        image: str | None = None,
        docker_binary: str = "docker",
        flow_args: Sequence[str] = DEFAULT_FLOW_ARGS,
        timeout_seconds: float | None = None,
        run_as_user: str | None = _UNSET,
        budget_journal: Path | str | None = None,
        preflight: bool = True,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.image = image or os.environ.get(OPM_IMAGE_ENV, DEFAULT_OPM_IMAGE)
        self.docker_binary = docker_binary
        self.flow_args = tuple(flow_args)
        self.timeout_seconds = timeout_seconds
        self.run_as_user = default_run_as_user() if run_as_user is _UNSET else run_as_user
        self.budget_journal = Path(budget_journal) if budget_journal is not None else None
        self.preflight = preflight

    def image_reference(self) -> ImageReference:
        return resolve_image_reference(
            image=self.image, docker_binary=self.docker_binary
        )


    def run(
        self,
        deck: EmittedOpmDeck,
        schedule: Schedule,
        *,
        run_id: str | None = None,
        flow_args: Sequence[str] | None = None,
    ) -> RunResult:

        run_id = run_id or self.new_run_id()
        started = time.perf_counter()
        try:
            hashes = deck_hashes(deck, schedule)
        except (OpmRunnerError, OSError, ValueError) as error:
            failed = RunResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                deck_hash="",
                canonical_schedule_hash="",
                summary_hash="",
                artifacts=(),
                wallclock_seconds=time.perf_counter() - started,
                message=f"ключ прогона не собран: {error}",
            )
            record_budget_entry(failed, journal=self.budget_journal)
            return failed
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

        run_id = run_id or self.new_run_id()
        started = time.perf_counter()

        def result(status: RunStatus, message: str, workdir: Path | None) -> RunResult:
            run_result = RunResult(
                run_id=run_id,
                status=status,
                deck_hash=deck_hash,
                canonical_schedule_hash=canonical_schedule_hash,
                summary_hash=summary_hash,
                artifacts=_collect_artifacts(workdir),
                wallclock_seconds=time.perf_counter() - started,
                message=message,
            )
            record_budget_entry(run_result, journal=self.budget_journal)
            return run_result

        data_file = Path(data_file).resolve()
        if self.preflight:
            try:
                ensure_docker_ready(image=self.image, docker_binary=self.docker_binary)
            except DockerPreflightError as error:
                return result(RunStatus.FAILED, error.report.message, None)
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
            return result(
                RunStatus.FAILED,
                f"не удалось запустить {self.docker_binary!r}: {error}",
                workdir,
            )

        returncode = completed.returncode
        marker = _first_marker(log_file, _NOT_CONVERGED_MARKERS)
        if marker is None and _unrecovered_iteration_limit_failure(log_file):
            marker = _ITERATION_LIMIT_MARKER
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
            f"flow завершился кодом 0, образ {self.image_reference().image}; "
            f"лог: {log_file}",
            workdir,
        )


    @staticmethod
    def new_run_id() -> str:

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
        user = ["--user", self.run_as_user] if self.run_as_user else []
        return [
            self.docker_binary,
            "run",
            "--rm",
            *user,
            "--name",
            container,
            "-v",
            f"{mount_path(data_file.parent)}:/deck:ro",
            "-v",
            f"{mount_path(output_dir)}:/out",
            self.image,
            "flow",
            f"/deck/{data_file.name}",
            "--output-dir=/out",
            *args,
        ]

    def _force_remove_container(self, container: str) -> None:

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

    if workdir is None:
        return ()
    try:
        return tuple(
            str(path) for path in sorted(workdir.rglob("*")) if path.is_file()
        )
    except OSError:
        return ()
