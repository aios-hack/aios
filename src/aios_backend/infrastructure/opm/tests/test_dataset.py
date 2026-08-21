from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Sequence

import pytest

from aios_backend.infrastructure.opm.dataset import (
    CORES_PER_CONTAINER,
    DatasetError,
    DatasetGenerator,
    DatasetManifest,
    MANIFEST_NAME,
    PLAN_NAME,
    RunMetadata,
    dataset_hash,
    default_max_workers,
)
from aios_backend.infrastructure.opm.dataset_plan import (
    PerturbationFamily,
    PlanConfig,
    build_plan,
    dataset_base_schedule,
)
from aios_backend.infrastructure.opm.opm_deck import EmittedOpmDeck
from aios_backend.infrastructure.opm.runner import deck_hashes
from aios_backend.core.contracts import RunResult, RunStatus, Schedule

import conftest

MODEL_Z = conftest.model_z_dir()

pytestmark = pytest.mark.skipif(
    MODEL_Z is None, reason=conftest.missing_reason("Model_Z")
)

SEED = 20260816

SMALL = PlanConfig(
    n_level_scenarios=2,
    n_unreachable_scenarios=1,
    n_shutdown_scenarios=1,
    n_conversion_scenarios=1,
)


class _RecordingRunner:
    """Считает настоящие запуски и отдаёт готовый OK — без Docker и OPM.

    Подменяет только сам запуск симулятора: эмит дека, ключ из трёх хешей,
    кеш и манифест остаются настоящими. Это не мок отклика — отклик в этих
    тестах не загружается (`load_responses=False`), проверяется механика
    возобновления, а не физика.
    """

    def __init__(self, cache) -> None:
        self.cache = cache
        self.launched: list[str] = []
        self._lock = threading.Lock()

    def run(
        self,
        deck: EmittedOpmDeck,
        schedule: Schedule,
        *,
        run_id: str | None = None,
        flow_args: Sequence[str] | None = None,
    ) -> RunResult:
        hashes = deck_hashes(deck, schedule)
        cached = self.cache.lookup(
            hashes.deck_hash, hashes.canonical_schedule_hash, hashes.summary_hash
        )
        if cached is not None:
            return cached
        with self._lock:
            self.launched.append(hashes.canonical_schedule_hash)
            index = len(self.launched)
        result = RunResult(
            run_id=f"recorded-{index:04d}",
            status=RunStatus.OK,
            deck_hash=hashes.deck_hash,
            canonical_schedule_hash=hashes.canonical_schedule_hash,
            summary_hash=hashes.summary_hash,
            artifacts=(str(deck.data_file),),
            wallclock_seconds=0.0,
            message="записанный прогон",
        )
        self.cache.store(result)
        return result


def _generator(tmp_path: Path, *, max_workers: int = 2) -> tuple[DatasetGenerator, list]:
    holder: list[_RecordingRunner] = []

    def factory(_root: Path) -> _RecordingRunner:
        runner = _RecordingRunner(generator.cache)
        holder.append(runner)
        return runner

    generator = DatasetGenerator(
        MODEL_Z,
        tmp_path / "dataset",
        runner_factory=factory,
        max_workers=max_workers,
        load_responses=False,
    )
    return generator, holder


def test_plan_is_prepared_and_validated_before_any_run(tmp_path: Path) -> None:
    """`validate_static` проходит до эмита: невалидное не доходит до симулятора."""

    generator, holder = _generator(tmp_path)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)

    accepted, skipped = generator.prepare(plan)

    assert len(accepted) == len(plan)
    assert skipped == ()
    assert holder == []


def test_small_batch_runs_every_scenario_once(tmp_path: Path) -> None:
    generator, holder = _generator(tmp_path)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)

    report = generator.build(plan)

    assert len(report.samples) == len(plan)
    assert report.failed == ()
    assert report.n_simulated == len(plan)
    assert report.n_from_cache == 0
    assert len(holder[0].launched) == len(plan)
    assert set(report.by_family()) >= {
        PerturbationFamily.LEVELS,
        PerturbationFamily.UNREACHABLE,
        PerturbationFamily.SHUTDOWN,
        PerturbationFamily.CONVERSION,
    }


def test_resume_reuses_the_cache_instead_of_running_again(tmp_path: Path) -> None:
    """Приёмка: возобновление реально переиспользует кеш, а не считает заново.

    Манифест стирается, а генератор берётся новый: ни списка сделанного, ни
    памяти о первой партии не остаётся. Единственный путь не запустить
    симулятор здесь — попадание в кеш по тройке хешей (§4.5). Пары при этом
    обязаны вернуться все: возобновлённая партия — это датасет, а не пустой
    отчёт о том, что делать нечего.
    """

    generator, holder = _generator(tmp_path)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)
    first = generator.build(plan)
    assert first.n_simulated == len(plan)

    (generator.dataset_root / MANIFEST_NAME).unlink()

    second_generator, second_holder = _generator(tmp_path)
    second = second_generator.build(plan)

    assert second_holder[0].launched == []
    assert len(second.samples) == len(plan)
    assert second.n_from_cache == len(plan)
    assert second.n_simulated == 0


def test_resume_after_an_interruption_only_runs_what_is_missing(tmp_path: Path) -> None:
    """Прерванная партия продолжается: посчитанное не пересчитывается."""

    generator, holder = _generator(tmp_path)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)

    partial = generator.build(plan, limit=2)
    assert len(partial.samples) == 2
    assert len(holder[0].launched) == 2

    resumed_generator, resumed_holder = _generator(tmp_path)
    resumed = resumed_generator.build(plan)

    # Досчитано ровно недостающее, а вернулась партия целиком.
    assert len(resumed_holder[0].launched) == len(plan) - 2
    assert len(resumed.samples) == len(plan)
    assert resumed.n_from_cache == 2
    assert resumed.n_simulated == len(plan) - 2
    assert len(resumed_generator.manifest.completed_scenarios()) == len(plan)


def test_dataset_hash_is_stable_and_independent_of_run_order(tmp_path: Path) -> None:
    """Версия датасета — хеш плана и ключей прогонов, не порядка их появления."""

    generator, _ = _generator(tmp_path, max_workers=1)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)
    sequential = generator.build(plan)

    parallel_generator, _ = _generator(tmp_path / "parallel", max_workers=4)
    parallel = parallel_generator.build(plan)

    assert sequential.dataset_hash == parallel.dataset_hash
    assert sequential.plan_hash == parallel.plan_hash

    metadata = tuple(generator.manifest.read())
    assert dataset_hash(plan, metadata) == dataset_hash(plan, tuple(reversed(metadata)))


def test_dataset_hash_survives_a_second_pass_over_the_same_plan(tmp_path: Path) -> None:
    """Повтор партии не меняет версию датасета.

    Манифест дописывается построчно, поэтому второй проход кладёт по второй
    строке на тот же сценарий. Датасет от этого тот же — значит, и
    `dataset_hash` обязан совпасть. Ловилось только на настоящем прогоне
    (`test_dataset_opm.py`), пока хеш считался по списку, а не по множеству
    ключей.
    """

    generator, _ = _generator(tmp_path)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)

    first = generator.build(plan)
    second = generator.build(plan)

    assert second.n_simulated == 0
    assert second.n_from_cache == len(plan)
    assert len(generator.manifest.read()) == 2 * len(plan)
    assert second.dataset_hash == first.dataset_hash


def test_dataset_hash_changes_with_the_plan(tmp_path: Path) -> None:
    generator, _ = _generator(tmp_path)
    base = generator.base_schedule()
    first = generator.build(build_plan(base, seed=SEED, config=SMALL))

    other_generator, _ = _generator(tmp_path / "other")
    second = other_generator.build(build_plan(base, seed=SEED + 1, config=SMALL))

    assert first.dataset_hash != second.dataset_hash


def test_generation_is_deterministic_for_the_same_seed(tmp_path: Path) -> None:
    """Тот же seed — те же расписания и тот же dataset_hash."""

    first_generator, _ = _generator(tmp_path / "first")
    second_generator, _ = _generator(tmp_path / "second")
    base = first_generator.base_schedule()

    first = first_generator.build(build_plan(base, seed=SEED, config=SMALL))
    second = second_generator.build(build_plan(base, seed=SEED, config=SMALL))

    assert first.dataset_hash == second.dataset_hash
    assert [item.metadata.canonical_schedule_hash for item in first.samples] == [
        item.metadata.canonical_schedule_hash for item in second.samples
    ]


def test_metadata_carries_seed_status_unreachable_fraction_and_synthetic_flag(
    tmp_path: Path,
) -> None:
    """Метаданные §9.2 целиком, и флаг синтетики ложен для настоящих прогонов."""

    generator, _ = _generator(tmp_path)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)

    report = generator.build(plan)

    for sample in report.samples:
        metadata = sample.metadata
        assert metadata.synthetic is False
        assert metadata.status is RunStatus.OK
        assert metadata.seed != 0
        assert 0.0 <= metadata.unreachable_setpoint_fraction <= 1.0
        assert len(metadata.canonical_schedule_hash) == 64

    unreachable = [
        sample.metadata.unreachable_setpoint_fraction
        for sample in report.samples
        if sample.metadata.family is PerturbationFamily.UNREACHABLE
    ]
    assert unreachable and all(value > 0.0 for value in unreachable)


def test_synthetic_metadata_is_rejected_outright() -> None:
    """§9.2, §1.1: синтетика в этом канале запрещена, а не помечается флагом."""

    with pytest.raises(DatasetError, match="synthetic"):
        RunMetadata(
            scenario_id="x",
            family=PerturbationFamily.LEVELS,
            seed=1,
            spec_hash="a" * 64,
            canonical_schedule_hash="b" * 64,
            deck_hash="c" * 64,
            summary_hash="d" * 64,
            run_id="r",
            status=RunStatus.OK,
            unreachable_setpoint_fraction=0.0,
            wallclock_seconds=1.0,
            from_cache=False,
            synthetic=True,
        )


def test_manifest_is_append_only_and_survives_a_truncated_line(tmp_path: Path) -> None:
    """JSONL: прерванная запись не делает манифест нечитаемым целиком."""

    manifest = DatasetManifest(tmp_path / MANIFEST_NAME)
    metadata = RunMetadata(
        scenario_id="levels-0000",
        family=PerturbationFamily.LEVELS,
        seed=7,
        spec_hash="a" * 64,
        canonical_schedule_hash="b" * 64,
        deck_hash="c" * 64,
        summary_hash="d" * 64,
        run_id="r-1",
        status=RunStatus.OK,
        unreachable_setpoint_fraction=0.25,
        wallclock_seconds=12.5,
        from_cache=False,
    )
    manifest.append(metadata)
    with manifest.path.open("a", encoding="utf-8") as handle:
        handle.write('{"scenario_id": "оборван')

    assert manifest.read() == (metadata,)
    assert manifest.completed_scenarios() == frozenset({"levels-0000"})


def test_plan_file_is_written_next_to_the_manifest(tmp_path: Path) -> None:
    generator, _ = _generator(tmp_path)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)

    generator.build(plan)

    payload = json.loads((generator.dataset_root / PLAN_NAME).read_text(encoding="utf-8"))
    assert payload["plan_hash"] == plan.plan_hash
    assert payload["n_scenarios"] == len(plan)
    assert len(payload["scenarios"]) == len(plan)


def test_every_scenario_gets_its_own_deck_directory(tmp_path: Path) -> None:
    """Параллельные прогоны не делят изменяемых файлов: свой каталог на сценарий."""

    generator, _ = _generator(tmp_path, max_workers=4)
    plan = build_plan(generator.base_schedule(), seed=SEED, config=SMALL)

    generator.build(plan)

    decks = sorted(path.name for path in (generator.dataset_root / "decks").iterdir())
    assert decks == sorted(spec.scenario_id for spec in plan)


def test_default_worker_count_leaves_threads_to_the_solver() -> None:
    """Одновременных контейнеров меньше, чем ядер: Flow сам многопоточный."""

    cores = os.cpu_count() or 1
    workers = default_max_workers()

    assert 1 <= workers <= cores
    assert workers * CORES_PER_CONTAINER <= cores + CORES_PER_CONTAINER
