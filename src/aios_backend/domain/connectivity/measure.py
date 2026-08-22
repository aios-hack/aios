"""Вторая половина кампании: из прогонов OPM — матрица влияния λ и группы.

`campaign.py` гонит план через симулятор, этот модуль читает результат и
считает по нему λ. Разделение не косметическое: прогоны стоят часы и живут в
кеше, а разбор и регрессия — секунды и переигрываются сколько угодно раз, в
том числе на другом лаге и другом допуске недобора.

Три вещи здесь сделаны так, как требует контракт (§8.2), и ни одна из них не
подгоняется под красивый результат:

* **Регрессия идёт на фактическую приёмистость, а не на проектные уровни
  плана.** Скважина, которая не приняла заказанную воду, входит в матрицу
  воздействий тем, что реально приняла; проектный уровень остаётся только в
  сверке достижимости.
* **Отклик — накопленная добыча жидкости в окне, с перебором лага.** Лаг
  выбирается по максимуму пулированного `R²`, а не назначается.
* **Устойчивость меряется двумя независимыми партиями плана.** Одной партии
  мало по построению: `estimate_lambda` её и не примет.

Базовая линия берётся из настоящего базового прогона (`data/base_case/
response.json`, задача G1) — того же дека без перекладки, поэтому отдельного
прогона под неё кампания не тратит.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from aios_backend.core.contracts import IntervalResponse, Lambda, ResponseArtifact, StateAtDate
from aios_backend.core.paths import data_root
from aios_backend.infrastructure.opm.dataset import DatasetSample

from aios_backend.domain.connectivity.campaign import (
    BATCHES_PER_HALF,
    T0_DECK_DATE_INDEX,
    CampaignError,
    CampaignSetup,
    _factor,
)
from aios_backend.domain.connectivity.doe import DoEPlan, Level, achievability
from aios_backend.domain.connectivity.estimator import (
    Batch,
    LaggedObservations,
    ProducerObservation,
    best_lag,
    estimate_lambda,
    realized_drive,
    scan_lag,
)
from aios_backend.domain.connectivity.groups import GroupingParams, build_groups
from aios_backend.domain.connectivity.sweep import WindowSteps, cumulative_liquid, mean_injection_rate

#: Сетка лагов отклика в месяцах. Верх — половина окна: лаг длиннее половины
#: измеряемого хвоста нечем подтвердить внутри того же окна.
DEFAULT_LAGS = (0, 1, 2, 3, 4, 5, 6)

#: Регуляризация нормального уравнения. Не подгонка: план ортогонален, ridge
#: страхует от вырождения при выпавшем прогоне.
DEFAULT_RIDGE = 1e-6

#: Допуск недобора приёмистости: скважина, недобравшая больше, помечается как
#: недостижимая и её столбец объявляется ненадёжным (`achievability_ok`).
DEFAULT_TOLERANCE = 0.1

#: Ниже этого разделения по фактической приёмистости (м³/сут, разница средних
#: между уровнями HIGH и LOW) столбец считается не сдвинутым вовсе. Такая
#: скважина не «слабо влияет» — она не участвовала в эксперименте, и её
#: коэффициент определяется шумом. Порог берётся долей от шага амплитуды.
SEPARATION_FLOOR_SHARE = 0.1


@dataclass(frozen=True, slots=True)
class MeasurementReport:
    """Что получилось: сама λ и диагностика, по которой её можно оспорить."""

    influence: Lambda
    lag_scan: tuple[tuple[int, float], ...]
    n_runs_by_batch: tuple[int, ...]
    unreachable: tuple[str, ...]
    unmoved: tuple[str, ...] = ()

    @property
    def nonzero_edges(self) -> int:
        return sum(
            1 for row in self.influence.matrix for value in row if abs(value) > 0.0
        )


def _samples_by_scenario(samples: Sequence[DatasetSample]) -> dict[str, DatasetSample]:
    return {sample.metadata.scenario_id: sample for sample in samples}


def _batch_samples(
    samples: Sequence[DatasetSample], batch: int, plan: DoEPlan
) -> tuple[DatasetSample, ...]:
    by_id = _samples_by_scenario(samples)
    ordered: list[DatasetSample] = []
    for row in plan.rows:
        scenario_id = f"lambda-b{batch}-{row.run_index:04d}"
        sample = by_id.get(scenario_id)
        if sample is None:
            raise CampaignError(
                f"партия {batch}: нет прогона {scenario_id}. Строка плана без "
                f"отклика — дыра в матрице воздействий, дозаполнять её нечем"
            )
        if sample.response is None:
            raise CampaignError(f"{scenario_id}: отклик не разобран")
        ordered.append(sample)
    return tuple(ordered)


def _injection_by_run(
    samples: Sequence[DatasetSample], injectors: Sequence[str], steps: WindowSteps
) -> tuple[dict[str, float], ...]:
    rows: list[dict[str, float]] = []
    for sample in samples:
        assert sample.response is not None
        states = sample.response.state_at_date
        rows.append(
            {
                well: mean_injection_rate(states, well, T0_DECK_DATE_INDEX, steps)
                for well in injectors
            }
        )
    return tuple(rows)


def _baseline_injection(
    states: Sequence[StateAtDate], injectors: Sequence[str], steps: WindowSteps
) -> dict[str, float]:
    return {
        well: mean_injection_rate(states, well, T0_DECK_DATE_INDEX, steps)
        for well in injectors
    }


def _targets_by_run(
    plan: DoEPlan, baseline_by_well: Mapping[str, float]
) -> tuple[dict[str, float], ...]:
    """Цель прогона — та же, что реально заказана деку.

    `Amplitude.target` двигает уставку на абсолютный шаг (медиана ±10
    м³/сут), а кампания задаёт возмущение множителем от собственной уставки
    скважины (`campaign._factor`), потому что материализация датасета
    работает множителями. На скважине с медианным уровнем это одно и то же,
    на слабой — расходится вдвое, и сверка объявляла недостижимой скважину,
    у которой никто и не просил столько воды. Цель считается тем же
    множителем, иначе сверяется не с тем, что заказано.
    """

    return tuple(
        {
            well: baseline_by_well[well] * _factor(level, plan.amplitude)
            for well, level in row.levels.items()
        }
        for row in plan.rows
    )


def _observations(
    samples: Sequence[DatasetSample],
    baseline: ResponseArtifact,
    producers: Sequence[str],
    steps: WindowSteps,
    lag: int,
) -> LaggedObservations:
    shifted = WindowSteps(first=steps.first + lag, last=steps.last + lag)
    by_producer: dict[str, ProducerObservation] = {}
    for producer in producers:
        cumulative = tuple(
            cumulative_liquid(sample.response.interval_response, [producer], shifted)
            for sample in samples
            if sample.response is not None
        )
        by_producer[producer] = ProducerObservation(
            producer=producer,
            cumulative_by_run=cumulative,
            baseline_cumulative=cumulative_liquid(
                baseline.interval_response, [producer], shifted
            ),
        )
    return LaggedObservations(
        lag_months=lag, producers=tuple(producers), by_producer=by_producer
    )


def _movable(
    prepared: CampaignSetup,
    samples: Sequence[DatasetSample],
    injectors: Sequence[str],
    baseline_by_well: Mapping[str, float],
    steps: WindowSteps,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Разделить фонд окна на сдвинувшиеся и не сдвинувшиеся столбцы.

    Скважина, у которой средняя фактическая приёмистость на уровне HIGH не
    отличается от уровня LOW, в эксперименте не участвовала: дек просил
    больше воды, а симулятор её не принял — упор в забойное давление или в
    приёмистость пласта. Её коэффициент в регрессии определяется шумом, а
    вырожденный столбец рушит обусловленность всей матрицы, вместе с
    коэффициентами соседей. Такие столбцы исключаются из оценки и
    называются поимённо: «не измерено» — честный ответ, «0.0» — нет.
    """

    floor = prepared.amplitude.step_m3_per_day * SEPARATION_FLOOR_SHARE
    by_id = _samples_by_scenario(samples)
    high: dict[str, list[float]] = {well: [] for well in injectors}
    low: dict[str, list[float]] = {well: [] for well in injectors}
    for batch, plan in enumerate(prepared.plans):
        for row in plan.rows:
            sample = by_id.get(f"lambda-b{batch}-{row.run_index:04d}")
            if sample is None or sample.response is None:
                continue
            for well, level in row.levels.items():
                rate = mean_injection_rate(
                    sample.response.state_at_date, well, T0_DECK_DATE_INDEX, steps
                )
                (high if level is Level.HIGH else low)[well].append(
                    rate - baseline_by_well[well]
                )
    moved: list[str] = []
    stuck: list[str] = []
    for well in injectors:
        if not high[well] or not low[well]:
            stuck.append(well)
            continue
        separation = sum(high[well]) / len(high[well]) - sum(low[well]) / len(low[well])
        (moved if separation >= floor else stuck).append(well)
    return tuple(moved), tuple(stuck)


def measure(
    prepared: CampaignSetup,
    samples: Sequence[DatasetSample],
    baseline: ResponseArtifact,
    *,
    n_steps: int,
    lags: Sequence[int] = DEFAULT_LAGS,
    ridge: float = DEFAULT_RIDGE,
    tolerance: float = DEFAULT_TOLERANCE,
) -> MeasurementReport:
    """λ по двум партиям плана, с выбранным лагом и сверкой достижимости."""

    steps = WindowSteps(first=0, last=n_steps - 1)
    all_injectors = prepared.fund.injectors
    producers = prepared.fund.producers
    baseline_injection = _baseline_injection(baseline.state_at_date, all_injectors, steps)

    injectors, unmoved = _movable(
        prepared, samples, all_injectors, baseline_injection, steps
    )
    if len(injectors) < 2:
        raise CampaignError(
            f"сдвинулось {len(injectors)} нагнетательных из {len(all_injectors)}: "
            f"измерять связность нечем"
        )

    # Партии сливаются по BATCHES_PER_HALF в половину, и оценка строится на
    # половинах, а не на партиях. Причина арифметическая: строк плана 27, а
    # параметров регрессии с интерцептом 28 — одна партия недоопределена,
    # R² выходит единицей на любом лаге, коэффициенты определены с точностью
    # до ядра. Две партии в половине дают 54 наблюдения на 28 параметров.
    half_drives = []
    half_samples = []
    unreachable: set[str] = set()
    for start in range(0, len(prepared.plans), BATCHES_PER_HALF):
        chunk = range(start, min(start + BATCHES_PER_HALF, len(prepared.plans)))
        pooled_samples: list[DatasetSample] = []
        pooled_actual: list[dict[str, float]] = []
        for batch in chunk:
            plan = prepared.plans[batch]
            ordered = _batch_samples(samples, batch, plan)
            # Сверка достижимости идёт по всему фонду окна, включая
            # столбцы, выброшенные из оценки: недобор — это диагностика
            # эксперимента, и умалчивать о нём нельзя. В матрицу воздействий
            # попадают только сдвинувшиеся.
            actual_all = _injection_by_run(ordered, all_injectors, steps)
            report = achievability(
                plan, _targets_by_run(plan, baseline_injection), actual_all, tolerance
            )
            unreachable.update(
                well for well, ok in report.achievability_ok().items() if not ok
            )
            pooled_samples.extend(ordered)
            pooled_actual.extend(
                {well: row[well] for well in injectors} for row in actual_all
            )
        half_drives.append(
            realized_drive(injectors, tuple(pooled_actual), baseline_injection)
        )
        half_samples.append(tuple(pooled_samples))

    if len(half_drives) < 2:
        raise CampaignError(
            f"половин {len(half_drives)}: устойчивость меряется между двумя "
            f"независимыми половинами, партий для этого нужно "
            f"{2 * BATCHES_PER_HALF}"
        )
    for index, drive in enumerate(half_drives):
        if drive.n_runs <= len(injectors):
            raise CampaignError(
                f"половина {index}: наблюдений {drive.n_runs} при "
                f"{len(injectors) + 1} параметрах регрессии — система "
                f"недоопределена, R² будет единицей на любом лаге, а "
                f"коэффициенты определены с точностью до ядра"
            )

    drives = half_drives
    batch_samples = half_samples

    scans = scan_lag(
        drives[0],
        {
            lag: _observations(batch_samples[0], baseline, producers, steps, lag)
            for lag in lags
        },
        ridge,
    )
    chosen = best_lag(scans)

    batches = tuple(
        Batch(
            drive=drives[index],
            observations=_observations(
                batch_samples[index], baseline, producers, steps, chosen.lag_months
            ),
        )
        for index in range(len(drives))
    )
    influence = estimate_lambda(
        window=prepared.window,
        producers=producers,
        batches=batches,
        lag_months=chosen.lag_months,
        amplitude=prepared.amplitude.step_m3_per_day,
        achievability_ok={well: well not in unreachable for well in injectors},
        ridge=ridge,
    )
    return MeasurementReport(
        influence=influence,
        lag_scan=tuple((scan.lag_months, scan.r_squared) for scan in scans),
        n_runs_by_batch=tuple(len(item) for item in batch_samples),
        unreachable=tuple(sorted(unreachable)),
        unmoved=unmoved,
    )


def save_lambda(measured: MeasurementReport, path: Path) -> Path:
    """Записать измеренную λ рядом с прогонами, из которых она получена.

    Формат — тот же JSON, что читает `load_lambda`: матрица вместе с окном
    применимости, лагом, диагностикой обусловленности и устойчивости и
    развёрткой по лагам. Диагностика лежит в одном файле с матрицей
    намеренно — λ без ранга, обусловленности и устойчивости невозможно ни
    оспорить, ни защитить.
    """

    influence = measured.influence
    path.write_text(
        json.dumps(
            {
                "window_start": influence.window_start.isoformat(),
                "window_end": influence.window_end.isoformat(),
                "lag_months": influence.lag_months,
                "amplitude": influence.amplitude,
                "rank": influence.rank,
                "condition_number": influence.condition_number,
                "stability": influence.stability,
                "producers": list(influence.producers),
                "injectors": list(influence.injectors),
                "matrix": [list(row) for row in influence.matrix],
                "achievability_ok": dict(influence.achievability_ok),
                "lag_scan": [list(item) for item in measured.lag_scan],
                "n_runs_by_batch": list(measured.n_runs_by_batch),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def load_lambda(path: Path | str) -> Lambda:
    """Прочитать измеренную λ. Отсутствие файла — не повод подставить нули.

    Нулевая матрица правильной формы выглядит как измерение и таковым не
    является: правило 3 репозитория запрещает подменять несчитанное
    правдоподобным. Поэтому здесь исключение, а не заглушка.
    """

    resolved = Path(path)
    if not resolved.is_file():
        raise CampaignError(
            f"измеренной λ нет по пути {resolved}: кампания замера "
            f"(`python -m connectivity.campaign`) ещё не отрабатывала, "
            f"подставлять нулевую матрицу вместо измерения запрещено"
        )
    data = json.loads(resolved.read_text(encoding="utf-8"))
    return Lambda(
        window_start=date.fromisoformat(data["window_start"]),
        window_end=date.fromisoformat(data["window_end"]),
        producers=tuple(data["producers"]),
        injectors=tuple(data["injectors"]),
        matrix=tuple(tuple(float(value) for value in row) for row in data["matrix"]),
        lag_months=int(data["lag_months"]),
        amplitude=float(data["amplitude"]),
        stability=float(data["stability"]),
        rank=int(data["rank"]),
        condition_number=float(data["condition_number"]),
        achievability_ok={well: bool(ok) for well, ok in data["achievability_ok"].items()},
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import os

    from aios_backend.infrastructure.opm.dataset import DatasetGenerator
    from aios_backend.infrastructure.resources import model_z_dir
    from aios_backend.domain.economics import load_response_artifact

    from aios_backend.domain.connectivity.campaign import DEFAULT_BATCH_SEEDS, DEFAULT_WINDOW_STEPS
    from aios_backend.domain.connectivity.campaign import campaign_plan, setup

    try:
        model_z = model_z_dir()
    except FileNotFoundError:
        print("дек Model_Z не найден", flush=True)
        return 2

    root = Path(
        os.environ.get(
            "AIOS_LAMBDA_ROOT",
            data_root() / "lambda-window-2007",
        )
    )
    n_steps = int(os.environ.get("AIOS_LAMBDA_STEPS", str(DEFAULT_WINDOW_STEPS)))
    baseline_path = data_root() / "base_case" / "response.json"

    generator = DatasetGenerator(model_z, root, max_workers=1, timeout_seconds=7200.0)
    prepared = setup(model_z, generator.base_schedule(), n_steps=n_steps)
    plan = campaign_plan(prepared, seed=DEFAULT_BATCH_SEEDS[0])

    # Прогоны уже в кеше: этот `build` ничего не считает, он их поднимает.
    report = generator.build(plan)
    if report.failed:
        print(f"упавших прогонов {len(report.failed)} — λ на дырявой матрице не считается", flush=True)
        return 3

    baseline = load_response_artifact(baseline_path)
    measured = measure(prepared, report.samples, baseline, n_steps=n_steps)

    print(f"лаг: {measured.influence.lag_months} мес", flush=True)
    print(
        "развёртка R²: "
        + ", ".join(f"{lag}={value:.3f}" for lag, value in measured.lag_scan),
        flush=True,
    )
    print(
        f"ранг {measured.influence.rank} из {len(measured.influence.injectors)} "
        f"столбцов (фонд окна {len(prepared.fund.injectors)}), "
        f"обусловленность {measured.influence.condition_number:.1f}, "
        f"устойчивость {measured.influence.stability:.3f}",
        flush=True,
    )
    print(
        f"ненулевых рёбер {measured.nonzero_edges} из "
        f"{len(measured.influence.producers) * len(measured.influence.injectors)}, "
        f"недостижимых нагнетательных {len(measured.unreachable)}, "
        f"не сдвинулось {len(measured.unmoved)}"
        + (f" ({', '.join(measured.unmoved)})" if measured.unmoved else ""),
        flush=True,
    )

    out = save_lambda(measured, root / "lambda.json")
    print(f"матрица записана: {out}", flush=True)

    groups, grouping = build_groups(measured.influence, GroupingParams())
    print(
        f"групп из λ: {len(groups.groups)}, покрытие "
        f"{sum(len(wells) for wells in groups.groups.values())} скважин",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
