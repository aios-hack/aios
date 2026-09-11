"""Интерфейс `θ → {objective, feasible, violations_by_scenario, provenance}`.

Контракт — docs/context/08_contracts.md §6.1:

    Policy:     FieldState + Constraints + Groups + θ  → Schedule + Trace
    Optimizer:  θ → {objective, feasible, violations_by_scenario, provenance}

Оптимизатор двигает ≤10 чисел `Theta` и не знает ни фонда, ни расписания:
`Objective.__call__` — единственная точка, через которую он получает число.
На входе и выходе — только типы `contracts`, ни `Schedule`, ни `well`, ни
`FieldState` здесь не появляются даже транзитивно через сигнатуры.

Скаляра недостаточно (`contracts/policy.py:48`): устойчивость — это
ограничение, не штраф. Поэтому `objective` считается **только** на
номинальном сценарии (`nominal`), а батарея сценариев (`battery`) может
только заполнить `violations_by_scenario` и снять `feasible` — свернуть
просадку батареи обратно в `objective` эта функция структурно не может, не
изменившись сама: сложение здесь никогда не встречается.

Что стоит за `nominal` и `battery` — не предмет этого файла. Реальная
оценка идёт через Policy (Иван) → прогон/суррогат → Economics (Савелий);
до тех пор, пока эти компоненты не готовы, они не притворяются нулём —
вызывающая сторона обязана передать проверяемую реализацию либо не
вызывать `Objective` вовсе.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.core.contracts import OptimizerResult, ScenarioViolation, Theta


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """Один сценарий батареи на конкретной θ: просадка и что нарушено.

    `feasible=True` при `regret=0.0` и пустом `what` — сценарий ничего не
    нарушил. Единица информации на сценарий, суммировать по батарее нельзя:
    это ровно то, что превратило бы ограничение в штраф.
    """

    regret: float
    feasible: bool
    what: str


class NominalObjective(Protocol):
    """θ → ЧДД по Методике на номинальном сценарии. Единственный источник
    `OptimizerResult.objective` — батарея в него не подмешивается."""

    def __call__(self, theta: Theta) -> float: ...


class ScenarioEvaluator(Protocol):
    """Один сценарий батареи: θ → просадка/нарушение на этом сценарии.

    `scenario_id` — то же имя, что уйдёт в `ScenarioViolation.scenario_id`;
    держать его при объекте, а не собирать заново на каждый вызов.
    """

    scenario_id: str

    def __call__(self, theta: Theta) -> ScenarioOutcome: ...


class ProvenanceSource(Protocol):
    """θ → хеши, которые обязаны сопровождать результат: суррогата,
    `Groups`, версии датасета, seed (contracts/policy.py:54)."""

    def __call__(self, theta: Theta) -> dict[str, str]: ...


class Objective:
    """θ → `OptimizerResult`. Композиция, а не вычисление: связывает
    номинальную цель и батарею сценариев так, что нарушение сценария не
    может попасть в `objective` иначе как через отдельное поле
    `violations_by_scenario`.
    """

    def __init__(
        self,
        nominal: NominalObjective,
        battery: tuple[ScenarioEvaluator, ...],
        provenance: ProvenanceSource,
    ) -> None:
        ids = [scenario.scenario_id for scenario in battery]
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        if duplicates:
            raise ValueError(f"scenario_id повторяется в батарее: {sorted(duplicates)}")
        self._nominal = nominal
        self._battery = battery
        self._provenance = provenance

    def __call__(self, theta: Theta) -> OptimizerResult:
        objective = self._nominal(theta)

        violations: list[ScenarioViolation] = []
        feasible = True
        for scenario in self._battery:
            outcome = scenario(theta)
            if not outcome.feasible:
                feasible = False
                violations.append(
                    ScenarioViolation(
                        scenario_id=scenario.scenario_id,
                        regret=outcome.regret,
                        what=outcome.what,
                    )
                )

        return OptimizerResult(
            objective=objective,
            feasible=feasible,
            violations_by_scenario=tuple(violations),
            provenance=self._provenance(theta),
        )
