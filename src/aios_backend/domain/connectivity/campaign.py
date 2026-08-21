"""Кампания замера λ: план Плакетта—Бермана → прогоны OPM → матрица влияния.

Чего здесь не было до 20.08. `connectivity/` умеет всё по отдельности —
нарезать окна (`fund`), строить план (`doe`), назначать уставки (`sweep`),
считать регрессию (`estimator`), резать группы (`groups`), — и всё это
покрыто тестами на синтетической матрице. Не было связки, которая гонит план
через настоящий симулятор: λ в проекте ни разу не измерялась, в артефакте
интерфейса лежит нулевая заглушка (`ui/base_artifact.py`), и правило R1 на
ней душит закачку по всему фонду.

Этот модуль — недостающее звено, и он намеренно не заводит своего прогонщика.
`Runner` объявлен общим сервисом с двумя потребителями — генератором датасета
и замером λ (`contracts/README.md`, «Два общих сервиса»), поэтому кампания
переиспользует `bridge.DatasetGenerator` целиком: параллельность, кеш по
тройке хешей, манифест, компактизация и возобновление прерванного прогона уже
там и переписывать их значило бы завести вторую реализацию того же.

Строка плана Плакетта—Бермана переводится в `PerturbationSpec` семейства
`LEVELS`: множитель к базовой уставке нагнетательной, действующий с первого
шага окна до конца горизонта. Возмущение не обрывается на границе окна
намеренно — отклик меряется накопленной добычей внутри окна с перебором лага,
и обрыв уставки внутри измеряемого хвоста портил бы именно его.

Приёмка модуля — не тест на синтетике, а полученная из настоящих прогонов
`Lambda` с ненулевыми рёбрами и записанным окном применимости.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from aios_backend.core.contracts import N_CONTROL_DATES, Role, Schedule
from aios_backend.core.contracts.response import N_DECK_DATES
from aios_backend.infrastructure.opm.dataset_plan import (
    LevelPerturbation,
    PerturbationFamily,
    PerturbationPlan,
    PerturbationSpec,
    PlanConfig,
)

from aios_backend.domain.connectivity.deck import parse_deck_schedule
from aios_backend.domain.connectivity.doe import Amplitude, DoEPlan, Level, amplitude_from_prior, plackett_burman
from aios_backend.domain.connectivity.fund import ActiveFund, Window, active_fund_in_window, build_fund_history
from aios_backend.domain.connectivity.setpoints import setpoint_changes

#: Первый управляющий шаг — 01.01.2007. Его индекс выводится из размеров
#: осей, а не повторяет число из конкретного дека.
T0_DECK_DATE_INDEX = N_DECK_DATES - N_CONTROL_DATES

#: Окно замера по умолчанию: два года управления, 24 замкнутых интервала.
DEFAULT_WINDOW_STEPS = 24

#: Доля распределения фактических шагов уставки, накрываемая амплитудой (§8.3).
DEFAULT_COVERAGE = 0.8

#: Четыре партии плана, а не две. Причина арифметическая и обнаружилась на
#: первых 54 прогонах: план Плакетта—Бермана на 27 нагнетательных даёт 27
#: строк, а регрессия с интерцептом требует 28 параметров — одна партия
#: недоопределена, R² выходит единицей на любом лаге, а коэффициенты
#: определены с точностью до ядра. Две партии, слитые в одну оценку, дают
#: 54 наблюдения на 28 параметров (26 степеней свободы, R² около 0.9995);
#: устойчивость §8.2 меряется между двумя такими слитыми половинами, значит
#: партий нужно четыре.
DEFAULT_BATCH_SEEDS = (20260820, 20260821, 20260822, 20260823)

#: Сколько партий сливается в одну оценку. Половины обязаны быть
#: независимыми: партии не пересекаются ни строками, ни сидом.
BATCHES_PER_HALF = 2


class CampaignError(ValueError):
    """Кампанию нельзя собрать однозначно из дека и базового расписания."""


@dataclass(frozen=True, slots=True)
class CampaignSetup:
    """Всё, что определено до первого прогона: окно, фонд, план, амплитуда."""

    window: Window
    fund: ActiveFund
    amplitude: Amplitude
    plans: tuple[DoEPlan, ...]

    @property
    def n_runs(self) -> int:
        return sum(len(plan.rows) for plan in self.plans)


def setup(
    model_dir: Path | str,
    base: Schedule,
    *,
    n_steps: int = DEFAULT_WINDOW_STEPS,
    coverage: float = DEFAULT_COVERAGE,
    batch_seeds: Sequence[int] = DEFAULT_BATCH_SEEDS,
) -> CampaignSetup:
    """Окно, активный фонд нагнетательных, амплитуда и по плану на партию."""

    if len(batch_seeds) < 2 * BATCHES_PER_HALF:
        raise CampaignError(
            f"партий {len(batch_seeds)}: устойчивость λ меряется двумя "
            f"независимыми половинами по {BATCHES_PER_HALF} партии (§8.2), "
            f"а одна партия на {len(batch_seeds)} сидах недоопределена — "
            f"строк плана меньше, чем параметров регрессии"
        )
    deck = parse_deck_schedule(Path(model_dir) / "Model_Z_sch.inc")
    start = deck.dates[T0_DECK_DATE_INDEX]
    end = deck.dates[T0_DECK_DATE_INDEX + n_steps]
    window = Window(start=start, end=end)

    history = build_fund_history(deck)
    fund = active_fund_in_window(deck, window, history)
    if not fund.injectors:
        raise CampaignError(f"в окне {start}…{end} нет активных нагнетательных")

    distribution = setpoint_changes(deck, Role.INJ, T0_DECK_DATE_INDEX)
    amplitude = amplitude_from_prior(distribution, coverage)

    plans = tuple(
        plackett_burman(window, fund, amplitude, seed) for seed in batch_seeds
    )
    return CampaignSetup(window=window, fund=fund, amplitude=amplitude, plans=plans)


def _factor(level: Level, amplitude: Amplitude) -> float:
    """Множитель к базовой уставке: шаг амплитуды в долях медианного уровня.

    Множитель, а не абсолютная уставка, потому что материализация датасета
    работает множителями (`LevelPerturbation`), а фактические уровни скважин
    различаются на порядок: общий абсолютный шаг увёл бы слабые скважины в
    ноль, а сильные не тронул.
    """

    relative = amplitude.step_m3_per_day / amplitude.base_level_m3_per_day
    if level is Level.HIGH:
        return 1.0 + relative
    factor = 1.0 - relative
    if factor <= 0.0:
        raise CampaignError(
            f"нижний уровень плана обнуляет уставку (множитель {factor}): "
            f"остановка скважины — не возмущение амплитуды"
        )
    return factor


def specs_of(plan: DoEPlan, batch: int, first_step: int = 0) -> tuple[PerturbationSpec, ...]:
    """Строки плана как сценарии датасета семейства `LEVELS`."""

    specs: list[PerturbationSpec] = []
    for row in plan.rows:
        levels = tuple(
            LevelPerturbation(
                well=well,
                from_step=first_step,
                factor=_factor(level, plan.amplitude),
            )
            for well, level in sorted(row.levels.items())
        )
        specs.append(
            PerturbationSpec(
                scenario_id=f"lambda-b{batch}-{row.run_index:04d}",
                family=PerturbationFamily.LEVELS,
                seed=plan.seed + row.run_index,
                levels=levels,
            )
        )
    return tuple(specs)


def campaign_plan(setup_result: CampaignSetup, seed: int) -> PerturbationPlan:
    """План кампании целиком: обе партии одним списком сценариев."""

    specs: list[PerturbationSpec] = []
    for batch, plan in enumerate(setup_result.plans):
        specs.extend(specs_of(plan, batch))
    return PerturbationPlan(config=PlanConfig(), seed=seed, specs=tuple(specs))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import conftest
    from aios_backend.infrastructure.opm.dataset import DatasetGenerator

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
    workers = int(os.environ.get("AIOS_LAMBDA_WORKERS", "3"))
    limit_text = os.environ.get("AIOS_LAMBDA_LIMIT")
    limit = int(limit_text) if limit_text else None
    n_steps = int(os.environ.get("AIOS_LAMBDA_STEPS", str(DEFAULT_WINDOW_STEPS)))

    root.mkdir(parents=True, exist_ok=True)
    generator = DatasetGenerator(model_z, root, max_workers=workers, timeout_seconds=7200.0)
    prepared = setup(model_z, generator.base_schedule(), n_steps=n_steps)
    plan = campaign_plan(prepared, seed=DEFAULT_BATCH_SEEDS[0])

    print(
        f"окно {prepared.window.start}…{prepared.window.end}, "
        f"нагнетательных {len(prepared.fund.injectors)}, "
        f"партий {len(prepared.plans)}, прогонов {prepared.n_runs}"
        + (f", ограничение {limit}" if limit else ""),
        flush=True,
    )
    print(
        f"амплитуда: медиана {prepared.amplitude.base_level_m3_per_day:.1f} м³/сут, "
        f"шаг {prepared.amplitude.step_m3_per_day:.1f} м³/сут "
        f"({prepared.amplitude.step_m3_per_day / prepared.amplitude.base_level_m3_per_day:.0%} уровня), "
        f"воркеров {workers}",
        flush=True,
    )

    started = time.monotonic()
    report = generator.build(plan, limit=limit)
    elapsed = time.monotonic() - started
    print(
        f"готово за {elapsed / 60:.1f} мин: посчитано {report.n_simulated}, "
        f"из кеша {report.n_from_cache}, пропущено {len(report.skipped)}, "
        f"упало {len(report.failed)}",
        flush=True,
    )
    for item in report.failed:
        print(f"  FAILED {item.message}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
