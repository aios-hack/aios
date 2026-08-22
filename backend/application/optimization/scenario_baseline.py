"""Сценарный бейзлайн и regret по батарее — задача 42, §13.1 и §13.3.

Задача 41 дала учётную часть: `ScenarioOutcome` принимает `npv_ours` и
`npv_scenario_baseline` готовыми и умеет считать по ним regret, нарушения и
разбивку. Откуда берётся второе число, она не знает. Здесь оно берётся.

## Почему бейзлайн нельзя взять номинальный

§13.1 говорит прямо: «Сравнивать с номинальным ЧДД нельзя. Сценарий
"половина фонда в ремонте" просядет у любого плана, и величина просадки
скажет о тяжести сценария, а не о качестве политики».

    regret(θ, s) = ЧДД лучшего плана для сценария s − ЧДД нашего плана при θ

Оба слагаемых считаются **внутри сценария**. Уменьшаемое — не номинал и не
константа: это тот же контур, перезапущенный с оптимизацией θ под
`Constraints` этого сценария. Поэтому задача 42 требует запуска
оптимизатора (задача 38) на каждый сценарий, а не только суррогата, и
стоит она столько же, сколько батарея умножить на бюджет поиска.

## Ограничение, а не слагаемое — и здесь тоже

Regret ограничивается порогом и никогда не складывается с ЧДД: свёрнутый в
цель, он потребовал бы вес, то есть одиннадцатую подгоняемую ручку сверх
≤10 (§13.3). Отчёт отдаёт `feasible` и разбивку по сценариям —
`robustness.regret.optimization_view` и `holdout_view` превращают их в ровно
ту пару, которую ждёт `OptimizerResult` (§6.1). Сложения по батарее здесь
нет ни одного.

## Бейзлайн слабее нашего плана — это диагностика, а не ноль

Бейзлайн — результат конечного поиска, а не точный максимум. Если поиск под
сценарий уложился в бюджет хуже, чем наш номинальный θ на том же сценарии,
regret выходит отрицательным. Обнулять его нельзя: отрицательный regret
означает не «мы идеальны», а «бейзлайн недосчитан», и это дефект замера,
который обязан быть виден. `BaselineSearch.underpowered` помечает такие
сценарии, а `RegretComputation.underpowered_scenarios` собирает их вместе,
чтобы отчёт нельзя было предъявить, не заметив.

## Seed

У каждого сценария свой seed, выведенный из seed батареи и идентификатора
сценария детерминированно. Один общий seed на все сценарии сделал бы
стартовые траектории поиска одинаковыми, а разные seed «на глазок» —
невоспроизводимыми. Требование сдачи — зафиксированный seed без
неконтролируемых случайных параметров (`config/schema.py`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, Sequence

from backend.core.contracts import Constraints, Theta

from backend.application.optimization.search import ObjectiveFunction, SearchReport, optimize
from backend.domain.robustness.battery import FragilityBattery, Scenario, Split
from backend.domain.robustness.regret import RegretReport, ScenarioOutcome


class ScenarioBaselineError(ValueError):
    """Бейзлайн нельзя посчитать: нет цели под сценарий, пустая батарея, нулевой бюджет."""


class ObjectiveFactory(Protocol):
    """Строит целевую функцию §6.1 под конкретные `Constraints`.

    Здесь проходит граница ответственности: `robustness/` знает, какие
    `Constraints` у сценария, и не знает, как из них получается ЧДД — это
    Policy (Иван) → суррогат или прогон (Андрей) → `Economics` (Савелий).
    Подменять эту цепочку заглушкой нельзя (правило 3): фабрика обязана
    вернуть считающую реализацию либо не вызываться вовсе.
    """

    def __call__(self, constraints: Constraints, scenario: Scenario) -> ObjectiveFunction: ...


def scenario_seed(battery_seed: int, scenario_id: str) -> int:
    """Детерминированный seed сценария из seed батареи и её идентификатора.

    Хеш, а не `battery_seed + индекс`: индекс меняется при любой вставке
    сценария в середину каталога, и вся батарея молча пересчитывается с
    другими траекториями поиска.
    """

    digest = hashlib.sha256(f"{battery_seed}:{scenario_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**31 - 1)


@dataclass(frozen=True, slots=True)
class BaselineSearch:
    """Переоптимизация θ под один сценарий: результат и его цена.

    `evaluations` и `stop_reason` хранятся не для красоты: бейзлайн, который
    упёрся в бюджет, и бейзлайн, который сошёлся, — это разные основания
    доверять числу regret.
    """

    scenario_id: str
    split: Split
    theta: Theta
    npv: float
    feasible: bool
    evaluations: int
    stop_reason: str
    seed: int
    underpowered: bool

    def __post_init__(self) -> None:
        if self.evaluations < 1:
            raise ScenarioBaselineError(
                f"{self.scenario_id}: бейзлайн без единой оценки"
            )


@dataclass(frozen=True, slots=True)
class RegretComputation:
    """Отчёт задачи 41 плюс то, чем он был получен.

    `report` — ровно `RegretReport`, который умеет `optimization_view` и
    `holdout_view`; `searches` — доказательство, что каждый бейзлайн
    посчитан перезапуском оптимизатора, а не взят номинальным.
    """

    report: RegretReport
    searches: tuple[BaselineSearch, ...]
    nominal_theta: Theta

    @property
    def total_evaluations(self) -> int:
        return sum(search.evaluations for search in self.searches)

    @property
    def underpowered_scenarios(self) -> tuple[str, ...]:
        return tuple(
            search.scenario_id for search in self.searches if search.underpowered
        )

    def search_of(self, scenario_id: str) -> BaselineSearch:
        for search in self.searches:
            if search.scenario_id == scenario_id:
                return search
        raise ScenarioBaselineError(f"сценария {scenario_id!r} нет в отчёте")


def scenario_baseline(
    scenario: Scenario,
    factory: ObjectiveFactory,
    nominal_theta: Theta,
    *,
    battery_seed: int,
    max_evaluations: int,
    base_constraints: Constraints | None = None,
) -> tuple[BaselineSearch, float]:
    """Свой ЧДД сценария и ЧДД нашего плана на нём.

    Возвращает пару `(бейзлайн, наш ЧДД под этим сценарием)`. Второе число —
    **не номинальный ЧДД**: наш θ пересчитывается под `Constraints`
    сценария, иначе разность мерила бы ещё и смену условий, а не только
    качество плана.
    """

    if max_evaluations < 1:
        raise ScenarioBaselineError(
            f"{scenario.scenario_id}: бюджет оценок {max_evaluations} < 1"
        )

    constraints = scenario.constraints(base_constraints)
    objective = factory(constraints, scenario)
    seed = scenario_seed(battery_seed, scenario.scenario_id)

    search: SearchReport = optimize(
        objective,
        nominal_theta,
        seed=seed,
        max_evaluations=max_evaluations,
    )

    ours = objective(nominal_theta)
    baseline_npv = search.best.result.objective

    return (
        BaselineSearch(
            scenario_id=scenario.scenario_id,
            split=scenario.split,
            theta=search.best.theta,
            npv=baseline_npv,
            feasible=search.best.result.feasible,
            evaluations=search.evaluations,
            stop_reason=search.stop_reason,
            seed=seed,
            underpowered=baseline_npv < ours.objective,
        ),
        ours.objective,
    )


def compute_regret(
    battery: FragilityBattery,
    factory: ObjectiveFactory,
    nominal_theta: Theta,
    *,
    threshold: float,
    max_evaluations_per_scenario: int,
    base_constraints: Constraints | None = None,
) -> RegretComputation:
    """Regret по всей батарее: на каждый сценарий свой перезапуск оптимизатора.

    Порядок сценариев — как в батарее, и он же порядок исходов: разбивка по
    сценариям обязательна (§13.1), её предъявляют интерфейс и защита, чтобы
    показать, на каком сценарии план проседает сильнее всего.
    """

    if not battery.scenarios:
        raise ScenarioBaselineError("пустая батарея ничего не меряет")

    searches: list[BaselineSearch] = []
    outcomes: list[ScenarioOutcome] = []

    for scenario in battery.scenarios:
        search, ours = scenario_baseline(
            scenario,
            factory,
            nominal_theta,
            battery_seed=battery.seed,
            max_evaluations=max_evaluations_per_scenario,
            base_constraints=base_constraints,
        )
        searches.append(search)
        outcomes.append(
            ScenarioOutcome(
                scenario_id=scenario.scenario_id,
                split=scenario.split,
                npv_ours=ours,
                npv_scenario_baseline=search.npv,
            )
        )

    return RegretComputation(
        report=RegretReport(
            outcomes=tuple(outcomes),
            threshold=threshold,
            battery_hash=battery.battery_hash(),
        ),
        searches=tuple(searches),
        nominal_theta=nominal_theta,
    )


def worst_scenarios(
    computation: RegretComputation, split: Split, limit: int = 3
) -> tuple[ScenarioOutcome, ...]:
    """Сценарии с наибольшим относительным regret — то, что показывают на
    защите, когда спрашивают, где план проседает сильнее всего."""

    if limit < 1:
        raise ScenarioBaselineError(f"limit={limit} < 1")
    outcomes = computation.report.of(split)
    return tuple(
        sorted(outcomes, key=lambda outcome: -outcome.relative_regret)[:limit]
    )


def evaluation_budget(battery: FragilityBattery, per_scenario: int) -> int:
    """Во сколько оценок обойдётся замер. Считается заранее, потому что
    каждая оценка — прогон или обращение к суррогату, и батарея умножает
    эту цену на число сценариев."""

    if per_scenario < 1:
        raise ScenarioBaselineError(f"бюджет на сценарий {per_scenario} < 1")
    return len(battery.scenarios) * per_scenario
