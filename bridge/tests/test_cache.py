from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bridge import CachingOpmRunner, OpmDeckEmitter, OpmRunner, RunCache, deck_hashes
from contracts import RunStatus, Schedule, ScheduleMeta, hash_schedule
from schedule import parse_schedule


from conftest import missing_reason, model_z_dir

DECKS = Path(__file__).resolve().parent / "decks"

# Через conftest, а не через parents[3]: см. тот же комментарий в test_runner.py.
MODEL_Z = model_z_dir()

requires_model_z = pytest.mark.skipif(
    MODEL_Z is None, reason=missing_reason("каталог Model_Z")
)

KEY = {
    "deck_hash": "d" * 64,
    "canonical_schedule_hash": "c" * 64,
    "summary_hash": "s" * 64,
}


@pytest.fixture(autouse=True)
def require_docker() -> None:
    if shutil.which("docker") is None:
        pytest.fail("для приёмки задачи 5 требуется Docker с настоящим OPM Flow")


def _baseline_schedule(emitter: OpmDeckEmitter) -> Schedule:
    parsed = parse_schedule((MODEL_Z / "Model_Z_sch.inc").read_bytes())
    return Schedule(
        meta=ScheduleMeta(wells=emitter.source_wells, provenance="Model_Z baseline"),
        initial_state={},
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


def _spy_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Считает реальные вызовы `subprocess.run` в bridge.runner, не подменяет их.

    Оборачивает оригинальную функцию: каждый вызов по-прежнему уходит в
    настоящий `docker run` / настоящий Flow, счётчик — только наблюдатель.
    Это и есть доказательство «второй запуск не стартовал симулятор» без
    подмены Docker фиктивным симулятором.
    """

    calls: list[list[str]] = []
    original = subprocess.run

    def spy(command, *args, **kwargs):
        calls.append(list(command))
        return original(command, *args, **kwargs)

    monkeypatch.setattr("bridge.runner.subprocess.run", spy)
    return calls


def test_second_call_with_same_key_hits_cache_without_starting_simulator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_subprocess_run(monkeypatch)
    runner = CachingOpmRunner(OpmRunner(tmp_path / "runs"), RunCache(tmp_path / "cache"))

    first = runner.run_data_file(DECKS / "MINI.DATA", **KEY)
    assert first.status is RunStatus.OK, first.message
    assert len(calls) == 1

    second = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    # Ключевое доказательство: docker run не вызывался второй раз.
    assert len(calls) == 1
    assert second.status is RunStatus.OK
    assert second.run_id == first.run_id
    assert second.artifacts == first.artifacts
    assert all(Path(path).is_file() for path in second.artifacts)


@pytest.mark.parametrize("changed_field", ["deck_hash", "canonical_schedule_hash", "summary_hash"])
def test_changing_any_of_three_hashes_is_a_cache_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_field: str
) -> None:
    calls = _spy_subprocess_run(monkeypatch)
    runner = CachingOpmRunner(OpmRunner(tmp_path / "runs"), RunCache(tmp_path / "cache"))

    first = runner.run_data_file(DECKS / "MINI.DATA", **KEY)
    assert first.status is RunStatus.OK, first.message
    assert len(calls) == 1

    changed_key = dict(KEY)
    changed_key[changed_field] = "9" * 64
    second = runner.run_data_file(DECKS / "MINI.DATA", **changed_key)

    # Другой ключ — реальный повторный прогон, а не кеш-попадание.
    assert len(calls) == 2
    assert second.status is RunStatus.OK, second.message
    assert second.run_id != first.run_id
    assert getattr(second, changed_field) == changed_key[changed_field]


def test_different_keys_do_not_collide_in_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_subprocess_run(monkeypatch)
    cache = RunCache(tmp_path / "cache")
    runner = CachingOpmRunner(OpmRunner(tmp_path / "runs"), cache)

    key_a = KEY
    key_b = {
        "deck_hash": "a" * 64,
        "canonical_schedule_hash": "b" * 64,
        "summary_hash": "e" * 64,
    }

    result_a = runner.run_data_file(DECKS / "MINI.DATA", **key_a)
    result_b = runner.run_data_file(DECKS / "MINI.DATA", **key_b)
    assert len(calls) == 2
    assert result_a.run_id != result_b.run_id

    # Оба ключа кешируются раздельно, попадания не путают результаты.
    cached_a = runner.run_data_file(DECKS / "MINI.DATA", **key_a)
    cached_b = runner.run_data_file(DECKS / "MINI.DATA", **key_b)
    assert len(calls) == 2
    assert cached_a.run_id == result_a.run_id
    assert cached_b.run_id == result_b.run_id

    first_dir = tmp_path / "runs" / result_a.run_id
    second_dir = tmp_path / "runs" / result_b.run_id
    assert first_dir.is_dir() and second_dir.is_dir()
    assert set(result_a.artifacts).isdisjoint(result_b.artifacts)
    assert all(Path(path).is_file() for path in (*result_a.artifacts, *result_b.artifacts))


def test_not_converged_result_is_cached_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_subprocess_run(monkeypatch)
    runner = CachingOpmRunner(OpmRunner(tmp_path / "runs"), RunCache(tmp_path / "cache"))

    first = runner.run_data_file(
        DECKS / "NOCONV.DATA",
        flow_args=("--parsing-strictness=low", "--enable-tuning=true"),
        **KEY,
    )
    assert first.status is RunStatus.NOT_CONVERGED, first.message
    assert len(calls) == 1

    second = runner.run_data_file(
        DECKS / "NOCONV.DATA",
        flow_args=("--parsing-strictness=low", "--enable-tuning=true"),
        **KEY,
    )

    assert len(calls) == 1
    assert second.status is RunStatus.NOT_CONVERGED
    assert second.run_id == first.run_id


def test_failed_result_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy_subprocess_run(monkeypatch)
    runner = CachingOpmRunner(OpmRunner(tmp_path / "runs"), RunCache(tmp_path / "cache"))

    first = runner.run_data_file(tmp_path / "no-such-deck.DATA", **KEY)
    assert first.status is RunStatus.FAILED
    assert "дек не найден" in first.message

    second = runner.run_data_file(tmp_path / "no-such-deck.DATA", **KEY)
    assert second.status is RunStatus.FAILED
    assert second.run_id != first.run_id


@requires_model_z
def test_runs_emitted_model_z_deck_through_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_subprocess_run(monkeypatch)
    emitter = OpmDeckEmitter(MODEL_Z)
    schedule = _baseline_schedule(emitter)
    deck = emitter.emit(schedule, tmp_path / "deck")

    runner = CachingOpmRunner(OpmRunner(tmp_path / "runs"), RunCache(tmp_path / "cache"))
    flow_args = ("--parsing-strictness=low", "--enable-dry-run=true")

    first = runner.run(deck, schedule, flow_args=flow_args)
    assert first.status is RunStatus.OK, first.message
    assert first.canonical_schedule_hash == hash_schedule(schedule)
    assert first.deck_hash == deck_hashes(deck, schedule).deck_hash
    assert len(calls) == 1

    second = runner.run(deck, schedule, flow_args=flow_args)

    assert len(calls) == 1
    assert second.status is RunStatus.OK
    assert second.run_id == first.run_id
    assert all(Path(path).is_file() for path in second.artifacts)
