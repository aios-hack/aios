from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.core.contracts import RunResult, RunStatus
from backend.contexts.simulation.infrastructure.runner import (
    BUDGET_CASE_ENV,
    BUDGET_INITIATOR_ENV,
    BUDGET_JOURNAL_ENV,
    BUDGET_JOURNAL_NAME,
    OpmRunner,
    budget_journal_path,
    record_budget_entry,
    resolve_case,
    resolve_initiator,
)
from tests.support.backend.paths import REPO_ROOT as _REPO_ROOT

REPO_ROOT = _REPO_ROOT
COLD_REPEAT = REPO_ROOT / "scripts" / "cold_repeat.sh"

_BASH_CANDIDATES = (
    "bash",
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    "/bin/bash",
    "/usr/bin/bash",
)


def _working_bash() -> str | None:
    for candidate in _BASH_CANDIDATES:
        resolved = shutil.which(candidate) or (
            candidate if Path(candidate).is_file() else None
        )
        if resolved is None:
            continue
        try:
            probe = subprocess.run(
                [resolved, "-c", "exit 0"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return resolved
    return None


BASH = _working_bash()

requires_bash = pytest.mark.skipif(
    BASH is None, reason="рабочий bash не найден: синтаксис shell-скрипта не проверить"
)


def _result(
    run_id: str = "run-1",
    *,
    status: RunStatus = RunStatus.OK,
    wallclock_seconds: float = 12.5,
    canonical_schedule_hash: str = "c" * 64,
) -> RunResult:
    return RunResult(
        run_id=run_id,
        status=status,
        deck_hash="d" * 64,
        canonical_schedule_hash=canonical_schedule_hash,
        summary_hash="s" * 64,
        artifacts=(),
        wallclock_seconds=wallclock_seconds,
        message="",
    )


def _lines(journal: Path) -> list[dict[str, object]]:
    text = journal.read_text(encoding="utf-8")
    assert text.endswith("\n")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_single_run_writes_exactly_one_line_with_filled_fields(tmp_path: Path) -> None:
    journal = tmp_path / BUDGET_JOURNAL_NAME
    record_budget_entry(_result(), journal=journal)

    entries = _lines(journal)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["run_id"] == "run-1"
    assert entry["canonical_schedule_hash"] == "c" * 64
    assert entry["wallclock_seconds"] == 12.5
    assert entry["status"] == "OK"
    assert entry["initiator"] == "test"
    assert entry["recorded_at"]


def test_two_runs_append_two_lines_without_overwriting(tmp_path: Path) -> None:
    journal = tmp_path / BUDGET_JOURNAL_NAME
    record_budget_entry(_result("run-1"), journal=journal)
    record_budget_entry(
        _result("run-2", status=RunStatus.NOT_CONVERGED, wallclock_seconds=7.0),
        journal=journal,
    )

    entries = _lines(journal)
    assert len(entries) == 2
    assert [entry["run_id"] for entry in entries] == ["run-1", "run-2"]
    assert [entry["status"] for entry in entries] == ["OK", "NOT_CONVERGED"]
    assert [entry["wallclock_seconds"] for entry in entries] == [12.5, 7.0]


@pytest.mark.parametrize(
    "wallclock",
    [float("nan"), float("inf"), float("-inf"), -1.0, "12.5", None, True],
)
def test_broken_wallclock_is_null_never_zero(tmp_path: Path, wallclock: object) -> None:
    journal = tmp_path / BUDGET_JOURNAL_NAME
    record_budget_entry(
        _result(wallclock_seconds=wallclock),  # type: ignore[arg-type]
        journal=journal,
    )

    entry = _lines(journal)[0]
    assert entry["wallclock_seconds"] is None
    assert entry["wallclock_seconds"] != 0.0


def test_zero_wallclock_is_kept_as_measured_value(tmp_path: Path) -> None:
    journal = tmp_path / BUDGET_JOURNAL_NAME
    record_budget_entry(_result(wallclock_seconds=0.0), journal=journal)

    assert _lines(journal)[0]["wallclock_seconds"] == 0.0


def test_initiator_comes_from_environment_over_pytest_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BUDGET_INITIATOR_ENV, "ui")
    assert resolve_initiator() == "ui"
    monkeypatch.setenv(BUDGET_INITIATOR_ENV, "CLI")
    assert resolve_initiator() == "cli"


def test_initiator_falls_back_to_test_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(BUDGET_INITIATOR_ENV, raising=False)
    assert resolve_initiator() == "test"


def test_initiator_is_unknown_without_environment_and_without_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(BUDGET_INITIATOR_ENV, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert resolve_initiator() == "unknown"


def test_case_is_the_constraints_file_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BUDGET_CASE_ENV, "config/competition-constraints.json")
    assert resolve_case() == "competition-constraints.json"
    monkeypatch.setenv(BUDGET_CASE_ENV, "   ")
    assert resolve_case() is None
    monkeypatch.delenv(BUDGET_CASE_ENV, raising=False)
    assert resolve_case() is None


def test_journal_path_honours_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nested" / "budget.jsonl"
    monkeypatch.setenv(BUDGET_JOURNAL_ENV, str(target))
    assert budget_journal_path() == target


def test_journal_default_is_out_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(BUDGET_JOURNAL_ENV, raising=False)
    monkeypatch.setenv("AIOS_OUT_DIR", str(tmp_path))
    assert budget_journal_path() == tmp_path / BUDGET_JOURNAL_NAME


def test_missing_deck_writes_one_line_for_the_failed_run(tmp_path: Path) -> None:
    journal = tmp_path / BUDGET_JOURNAL_NAME
    runner = OpmRunner(
        tmp_path / "runs",
        docker_binary="definitely-not-a-real-docker-binary",
        budget_journal=journal,
    )
    result = runner.run_data_file(
        tmp_path / "absent.DATA",
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
        run_id="run-missing-deck",
    )

    assert result.status is RunStatus.FAILED
    entries = _lines(journal)
    assert len(entries) == 1
    assert entries[0]["run_id"] == "run-missing-deck"
    assert entries[0]["status"] == "FAILED"
    assert isinstance(entries[0]["wallclock_seconds"], float)


def test_unwritable_journal_does_not_break_the_run(tmp_path: Path) -> None:
    journal = tmp_path / "runs"
    journal.mkdir()
    runner = OpmRunner(tmp_path / "work", budget_journal=journal)
    result = runner.run_data_file(
        tmp_path / "absent.DATA",
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
        run_id="run-unwritable",
    )

    assert result.status is RunStatus.FAILED
    assert journal.is_dir()


@requires_bash
def test_cold_repeat_script_has_valid_bash_syntax() -> None:
    assert COLD_REPEAT.is_file(), COLD_REPEAT
    completed = subprocess.run(
        [str(BASH), "-n", str(COLD_REPEAT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr


@requires_bash
def test_entrypoint_script_has_valid_bash_syntax() -> None:
    entrypoint = REPO_ROOT / "docker" / "entrypoint.sh"
    completed = subprocess.run(
        [str(BASH), "-n", str(entrypoint)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr


@requires_bash
def test_cold_repeat_script_refuses_without_run_id() -> None:
    completed = subprocess.run(
        [str(BASH), str(COLD_REPEAT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 64, completed.stdout + completed.stderr


@requires_bash
def test_cold_repeat_script_refuses_unknown_run(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            str(BASH),
            str(COLD_REPEAT),
            "--run-id",
            "absent-run",
            "--runs-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr


def test_entrypoint_forwards_arguments_for_every_command() -> None:
    entrypoint = REPO_ROOT / "docker" / "entrypoint.sh"
    text = entrypoint.read_text(encoding="utf-8")
    assert 'repeat) cmd_repeat "$@" ;;' in text
    assert 'bash /app/scripts/cold_repeat.sh "$@"' in text
