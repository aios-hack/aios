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
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from contracts import IntervalResponse, Lambda, ResponseArtifact, StateAtDate
from bridge.dataset import DatasetSample

from connectivity.campaign import T0_DECK_DATE_INDEX, CampaignSetup, CampaignError
from connectivity.doe import DoEPlan, Level, achievability
from connectivity.estimator import (
    Batch,
    LaggedObservations,
    ProducerObservation,
    best_lag,
    estimate_lambda,
    realized_drive,
    scan_lag,
)
from connectivity.groups import GroupingParams, build_groups
from connectivity.sweep import WindowSteps, cumulative_liquid, mean_injection_rate

#: Сетка лагов отклика в месяцах. Верх — половина окна: лаг длиннее половины
#: измеряемого хвоста нечем подтвердить внутри того же окна.
DEFAULT_LAGS = (0, 1, 2, 3, 4, 5, 6)

#: Регуляризация нормального уравнения. Не подгонка: план ортогонален, ridge
#: страхует от вырождения при выпавшем прогоне.
DEFAULT_RIDGE = 1e-6

#: Допуск недобора приёмистости: скважина, недобравшая больше, помечается как
#: недостижимая и её столбец объявляется ненадёжным (`achievability_ok`).
DEFAULT_TOLERANCE = 0.1


@dataclass(frozen=True, slots=True)
class MeasurementReport:
    """Что получилось: сама λ и диагностика, по которой её можно оспорить."""

    influence: Lambda
    lag_scan: tuple[tuple[int, float], ...]
    n_runs_by_batch: tuple[int, ...]
    unreachable: tuple[str, ...]

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
    return tuple(
        {
            well: plan.amplitude.target(level, baseline_by_well[well])
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
    injectors = prepared.fund.injectors
    producers = prepared.fund.producers
    baseline_injection = _baseline_injection(baseline.state_at_date, injectors, steps)

    drives = []
    batch_samples = []
    unreachable: set[str] = set()
    for batch, plan in enumerate(prepared.plans):
        ordered = _batch_samples(samples, batch, plan)
        actual = _injection_by_run(ordered, injectors, steps)
        report = achievability(
            plan, _targets_by_run(plan, baseline_injection), actual, tolerance
        )
        unreachable.update(
            well for well, ok in report.achievability_ok().items() if not ok
        )
        drives.append(realized_drive(injectors, actual, baseline_injection))
        batch_samples.append(ordered)

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
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import os

    import conftest
    from bridge.dataset import DatasetGenerator
    from economics import load_response_artifact

    from connectivity.campaign import DEFAULT_BATCH_SEEDS, DEFAULT_WINDOW_STEPS
    from connectivity.campaign import campaign_plan, setup

    model_z = conftest.model_z_dir()
    if model_z is None:
        print("дек Model_Z не найден", flush=True)
        return 2

    root = Path(
        os.environ.get(
            "AIOS_LAMBDA_ROOT",
            Path(__file__).resolve().parents[1] / "data" / "lambda-window-2007",
        )
    )
    n_steps = int(os.environ.get("AIOS_LAMBDA_STEPS", str(DEFAULT_WINDOW_STEPS)))
    baseline_path = Path(__file__).resolve().parents[1] / "data" / "base_case" / "response.json"

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
        f"ранг {measured.influence.rank} из {len(prepared.fund.injectors)}, "
        f"обусловленность {measured.influence.condition_number:.1f}, "
        f"устойчивость {measured.influence.stability:.3f}",
        flush=True,
    )
    print(
        f"ненулевых рёбер {measured.nonzero_edges} из "
        f"{len(measured.influence.producers) * len(measured.influence.injectors)}, "
        f"недостижимых нагнетательных {len(measured.unreachable)}",
        flush=True,
    )

    out = root / "lambda.json"
    out.write_text(
        json.dumps(
            {
                "window_start": measured.influence.window_start.isoformat(),
                "window_end": measured.influence.window_end.isoformat(),
                "lag_months": measured.influence.lag_months,
                "amplitude": measured.influence.amplitude,
                "rank": measured.influence.rank,
                "condition_number": measured.influence.condition_number,
                "stability": measured.influence.stability,
                "producers": list(measured.influence.producers),
                "injectors": list(measured.influence.injectors),
                "matrix": [list(row) for row in measured.influence.matrix],
                "achievability_ok": dict(measured.influence.achievability_ok),
                "lag_scan": [list(item) for item in measured.lag_scan],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
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
