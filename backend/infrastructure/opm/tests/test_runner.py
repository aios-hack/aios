from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.infrastructure.opm import OpmDeckEmitter, OpmRunner, deck_hashes
from backend.infrastructure.opm.runner import (
    OPM_USER_ENV,
    _ITERATION_LIMIT_MARKER,
    _NOT_CONVERGED_MARKERS,
    _RECOVERABLE_MARKERS,
    _first_marker,
    _unrecovered_iteration_limit_failure,
    summary_spec_hash,
)
from backend.core.contracts import RunStatus, Schedule, ScheduleMeta, SummarySpec, hash_schedule
from backend.domain.schedule import parse_schedule


from conftest import docker_unavailable_reason, missing_reason, model_z_dir

DECKS = Path(__file__).resolve().parent / "decks"

# Через conftest, а не через parents[3]: сиблинг-раскладка `../docs` — не
# единственная, docs бывает склонирован и внутрь рабочей копии, и задан
# переменной AIOS_DOCS_ROOT. Ровно этот хардкод интеграция уже снимала в ui.
MODEL_Z = model_z_dir()

# Скипается только то, что действительно смотрит в дек: остальным тестам
# файла хватает своих минимальных деков из DECKS.
requires_model_z = pytest.mark.skipif(
    MODEL_Z is None, reason=missing_reason("каталог Model_Z")
)

# Плейсхолдеры ключа: задача 4 отвечает за то, что RunResult донёс их без
# искажения, а не за их вычисление из Model_Z — это проверяется отдельно.
KEY = {
    "deck_hash": "d" * 64,
    "canonical_schedule_hash": "c" * 64,
    "summary_hash": "s" * 64,
}


# Раньше проверка стояла autouse-фикстурой и требовала лишь `docker` в PATH.
# Клиент есть и при остановленном демоне, поэтому такая проверка пропускала
# вперёд прогоны, отказывавшие статусом FAILED, — приёмка читала это как
# дефект Runner'а. Теперь доступность демона проверяется по-настоящему, а
# метка ставится точечно: разбор маркеров лога и обработка отказов запуска
# симулятора не требуют и работают без Docker.
requires_real_flow = pytest.mark.skipif(
    docker_unavailable_reason() is not None,
    reason=f"приёмка задачи 4 требует настоящий OPM Flow; {docker_unavailable_reason()}",
)


def _baseline_schedule(emitter: OpmDeckEmitter) -> Schedule:
    parsed = parse_schedule((MODEL_Z / "Model_Z_sch.inc").read_bytes())
    return Schedule(
        meta=ScheduleMeta(wells=emitter.source_wells, provenance="Model_Z baseline"),
        initial_state={},
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


@requires_real_flow
def test_successful_real_flow_run_is_ok_with_existing_artifacts(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert result.status is RunStatus.OK, result.message
    assert result.deck_hash == KEY["deck_hash"]
    assert result.canonical_schedule_hash == KEY["canonical_schedule_hash"]
    assert result.summary_hash == KEY["summary_hash"]
    assert result.wallclock_seconds > 0.0
    assert result.artifacts
    assert all(Path(path).is_file() for path in result.artifacts)

    produced = {Path(path).name for path in result.artifacts}
    assert {"flow.log", "command.txt"} <= produced
    assert {"MINI.UNSMRY", "MINI.SMSPEC", "MINI.PRT"} <= produced
    assert "docker" in (tmp_path / "runs" / result.run_id / "command.txt").read_text()


@requires_real_flow
def test_non_converging_real_run_is_not_converged_without_raising(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(
        DECKS / "NOCONV.DATA",
        flow_args=("--parsing-strictness=low", "--enable-tuning=true"),
        **KEY,
    )

    # Flow здесь завершается кодом 0: несходимость видна только в логе.
    assert result.status is RunStatus.NOT_CONVERGED, result.message
    assert "не сошёлся" in result.message
    assert any(marker in result.message for marker in _NOT_CONVERGED_MARKERS)
    assert result.artifacts


@requires_real_flow
def test_broken_deck_is_failed_without_raising(tmp_path: Path) -> None:
    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    broken = broken_dir / "BROKEN.DATA"
    broken.write_text(
        (DECKS / "MINI.DATA")
        .read_text(encoding="utf-8")
        .replace("\nDIMENS\n", "\nDIMENSXX\n"),
        encoding="utf-8",
    )

    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(broken, **KEY)

    assert result.status is RunStatus.FAILED, result.message
    assert "Unknown keyword" in result.message
    assert result.wallclock_seconds > 0.0


def test_missing_deck_is_failed_not_exception(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(tmp_path / "no-such-deck.DATA", **KEY)

    assert result.status is RunStatus.FAILED
    assert "дек не найден" in result.message


def test_unavailable_docker_is_failed_not_subprocess_exception(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs", docker_binary=str(tmp_path / "no-such-docker"))
    result = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert result.status is RunStatus.FAILED
    assert "не удалось запустить" in result.message


def test_timeout_is_failed_and_does_not_leak_a_container(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs", timeout_seconds=0.001)
    result = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert result.status is RunStatus.FAILED
    assert "не уложился" in result.message
    assert result.run_id in result.message


@requires_real_flow
def test_two_runs_use_separate_working_directories(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    first = runner.run_data_file(DECKS / "MINI.DATA", **KEY)
    second = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert first.status is RunStatus.OK, first.message
    assert second.status is RunStatus.OK, second.message
    assert first.run_id != second.run_id

    first_dir = tmp_path / "runs" / first.run_id
    second_dir = tmp_path / "runs" / second.run_id
    assert first_dir.is_dir() and second_dir.is_dir()
    assert set(first.artifacts).isdisjoint(second.artifacts)
    assert all(Path(path).is_file() for path in (*first.artifacts, *second.artifacts))


def test_recoverable_linear_solver_messages_are_not_non_convergence(tmp_path: Path) -> None:
    """Срезанный шаг — не отказ прогона: успешный Flow тоже это печатает."""

    log = tmp_path / "flow.log"
    log.write_text("\n".join(_RECOVERABLE_MARKERS) + "\n")

    assert _first_marker(log, _NOT_CONVERGED_MARKERS) is None


def test_iteration_limit_followed_by_chop_is_not_a_failure(tmp_path: Path) -> None:
    """Настоящий Model_Z 16.08: маркер встретился раз, Flow пересчитал шаг

    меньшим таймшагом и досчитал все 371 report step без дальнейших сбоев —
    не отказ прогона (§4.7 базы знаний).
    """

    log = tmp_path / "flow.log"
    log.write_text(
        f"    Oscillating behavior detected: Relaxation set to 0.500000\n\n"
        f"Problem: {_ITERATION_LIMIT_MARKER} - Iteration limit reached\n"
        f"Timestep chopped to 10.23 days\n\n\n"
        f"Starting time step 0, stepsize 10.23 days, at day 3257/3288\n"
    )

    assert _unrecovered_iteration_limit_failure(log) is False


def test_iteration_limit_without_chop_is_a_failure(tmp_path: Path) -> None:
    """Тот же маркер без пересчёта следом — Flow действительно снял прогон."""

    log = tmp_path / "flow.log"
    log.write_text(
        f"Problem: {_ITERATION_LIMIT_MARKER} - Iteration limit reached\n"
        "\n\n\n\n\n"
        "================    End of simulation     ===============\n"
    )

    assert _unrecovered_iteration_limit_failure(log) is True


@requires_model_z
@requires_real_flow
def test_runs_emitted_model_z_deck_through_real_flow(tmp_path: Path) -> None:
    """Путь `run(EmittedOpmDeck)` целиком, на настоящей Model_Z.

    Прогон в режиме разбора: полный расчёт Model_Z занимает неизвестное
    время и замеряется задачей 7, а здесь проверяется, что Runner монтирует
    эмитированный дек, доносит ключ и возвращает OK на настоящем Flow.
    """

    emitter = OpmDeckEmitter(MODEL_Z)
    schedule = _baseline_schedule(emitter)
    deck = emitter.emit(schedule, tmp_path / "deck")

    runner = OpmRunner(tmp_path / "runs")
    result = runner.run(
        deck,
        schedule,
        flow_args=("--parsing-strictness=low", "--enable-dry-run=true"),
    )

    assert result.status is RunStatus.OK, result.message
    assert result.canonical_schedule_hash == hash_schedule(schedule)
    assert result.deck_hash == deck_hashes(deck, schedule).deck_hash
    assert result.wallclock_seconds > 0.0
    assert all(Path(path).is_file() for path in result.artifacts)


@requires_model_z
def test_deck_hashes_bind_static_deck_schedule_and_summary_spec(tmp_path: Path) -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    schedule = _baseline_schedule(emitter)
    deck = emitter.emit(schedule, tmp_path / "deck")

    hashes = deck_hashes(deck, schedule)

    assert hashes.canonical_schedule_hash == hash_schedule(schedule)
    assert hashes.summary_hash == summary_spec_hash(SummarySpec())
    # Статика — не весь дек: content_hash_opm накрывает и управляющий слой.
    assert hashes.deck_hash != deck.content_hash_opm
    assert len(hashes.deck_hash) == 64


# --- Владелец файлов прогона -----------------------------------------------
#
# Образ opmreleases работает под uid 1001 (opm), каталог прогона создаёт хост.
# Совпадение uid — свойство одной машины, а не инварианта, и его расхождение
# отказывает не как отказ прав: Flow валится на «Failed to create valid
# EclipseState object», а настоящая причина уходит в .PRT, который он не смог
# открыть. Ниже — приёмка того, что uid хоста передаётся всегда.


@pytest.mark.skipif(
    not hasattr(os, "getuid"),
    reason="uid/gid — понятие POSIX: на Windows их нет ни у хоста, ни у тома",
)
def test_container_runs_as_the_host_user_by_default(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert "--user" in command
    expected = f"{os.getuid()}:{os.getgid()}"
    assert command[command.index("--user") + 1] == expected


def test_without_posix_uid_the_image_default_user_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows-хост: uid передавать нечего, и навязывать `--user` нельзя.

    Отображение владельца тома делает сам Docker Desktop, а строка вида
    `--user 0:0` только сломала бы то, что там уже работает.
    """

    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.delattr(os, "getgid", raising=False)
    monkeypatch.delenv(OPM_USER_ENV, raising=False)
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert "--user" not in command


def test_run_as_user_is_overridable_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPM_USER_ENV, "4242:4243")
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert command[command.index("--user") + 1] == "4242:4243"


def test_empty_override_restores_the_image_default_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пустая переменная — способ отдать выбор образу: в rootless-docker и
    podman отображение уже сделано демоном, и навязывать --user там вредно."""

    monkeypatch.setenv(OPM_USER_ENV, "")
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert "--user" not in command


# Регрессия на сам дефект — уже существующий
# `test_broken_deck_is_failed_without_raising`: он требует «Unknown keyword» в
# сообщении, и до этой правки получал «Failed opening file /out/BROKEN.PRT for
# StreamLog» — текст ошибки разбора оставался в файле, который Flow не смог
# создать. Отдельный тест на то же самое здесь был бы копией.
