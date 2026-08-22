from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.infrastructure.opm.dataset import DatasetGenerator
from backend.infrastructure.opm.dataset_plan import PerturbationFamily, PlanConfig, build_plan
from backend.core.contracts import N_INTERVALS, RunStatus

import conftest

MODEL_Z = conftest.model_z_dir()

pytestmark = pytest.mark.skipif(
    MODEL_Z is None, reason=conftest.missing_reason("Model_Z")
)

SEED = 20260816

# Малая партия: приёмка требует доказать, что генератор доводит сценарии до
# настоящего OPM, а не намолотить датасет. Полный прогон Model_Z — сотни
# секунд (задача 7), поэтому партия из четырёх сценариев и держится
# четырьмя одновременными контейнерами.
BATCH = PlanConfig(
    n_level_scenarios=1,
    n_unreachable_scenarios=1,
    n_shutdown_scenarios=1,
    n_conversion_scenarios=1,
    include_baseline=False,
)


# Четыре полных прогона Model_Z — это полчаса машинного времени. Каталог
# датасета выносится из pytest-tmp переменной окружения, чтобы повторный
# запуск приёмки поднимал их из кеша, а не считал заново; вне git (правило 9).
DATASET_ROOT_ENV_VAR = "AIOS_DATASET_ROOT"


@pytest.fixture(autouse=True)
def require_docker() -> None:
    reason = conftest.docker_unavailable_reason()
    if reason is not None:
        pytest.skip(f"приёмка задачи 30 требует настоящий OPM Flow; {reason}")


def _dataset_root(tmp_path: Path) -> Path:
    from_env = os.environ.get(DATASET_ROOT_ENV_VAR)
    return Path(from_env) if from_env else tmp_path / "dataset"


def test_small_batch_goes_through_real_opm_and_resumes_from_cache(tmp_path: Path) -> None:
    """Приёмка: малая партия действительно считается настоящим OPM.

    Проверяется всё, ради чего компонент существует: план доходит до
    симулятора, отклик разбирается в два типа (§4.1.1), метаданные §9.2
    заполнены, а повтор той же партии не запускает симулятор ни разу —
    возобновление держится на кеше по тройке хешей (§4.5).
    """

    generator = DatasetGenerator(
        MODEL_Z,
        _dataset_root(tmp_path),
        max_workers=4,
        timeout_seconds=3600.0,
    )
    plan = build_plan(generator.base_schedule(), seed=SEED, config=BATCH)
    assert len(plan) == 4

    report = generator.build(plan)

    assert report.skipped == ()
    assert report.failed == (), [item.message for item in report.failed]
    assert len(report.samples) == 4
    assert report.n_simulated + report.n_from_cache == 4
    assert set(report.by_family()) == {
        PerturbationFamily.LEVELS,
        PerturbationFamily.UNREACHABLE,
        PerturbationFamily.SHUTDOWN,
        PerturbationFamily.CONVERSION,
    }

    wells = len(generator.base_schedule().meta.wells)
    for sample in report.samples:
        assert sample.metadata.status is RunStatus.OK
        assert sample.metadata.synthetic is False
        assert sample.metadata.wallclock_seconds > 0.0
        assert sample.response is not None
        assert sample.response.source_run_id == sample.metadata.run_id
        assert len(sample.response.interval_response) == N_INTERVALS * wells
        assert sample.response.state_at_date

    # Отклики разных сценариев — разные: возмущение действительно доехало
    # до физики, а не осталось в расписании.
    response_hashes = {sample.metadata.response_hash for sample in report.samples}
    assert len(response_hashes) == len(report.samples)

    resumed = generator.build(plan)

    assert resumed.n_simulated == 0
    assert resumed.n_from_cache == 4
    assert len(resumed.samples) == 4
    assert resumed.dataset_hash == report.dataset_hash
