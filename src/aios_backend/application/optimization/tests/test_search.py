"""Приёмка задачи 38 (docs/v1/assignments/andrey.md, docs/context/08_contracts.md §6.1).

Карточка: «Оптимизатор — подключается после выбора семейства
(`07_concept.md` §8.2)». Семейство выбрано — CMA-ES, обоснование в
докстринге `optimizer/search.py`. Приёмка складывается из того, что §6.1
требует от границы, и из того, что обязано быть верно у любого поиска,
который эту границу двигает:

1. подключается к `Objective` из задачи 37 и двигает θ, а не что-то своё;
2. ограничение устойчивости не сворачивается в штраф — недопустимая точка
   не выигрывает ни при каком `objective`;
3. по батарее по-прежнему не суммируется;
4. объявленные границы θ не нарушаются ни одной оценённой точкой;
5. воспроизводимо при фиксированном seed;
6. бюджет оценок жёсткий — вызовов не больше заявленного;
7. оптимизатор не видит ни скважин, ни расписания.
"""

from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path
from typing import get_type_hints

import pytest

from aios_backend.core.contracts import OptimizerResult, ScenarioViolation, Theta
from aios_backend.application.optimization import Objective, ScenarioOutcome
from aios_backend.application.optimization.search import (
    Evaluation,
    OptimizerError,
    SearchReport,
    default_population,
    is_better,
    optimize,
)

BOUNDS = {"a": (0.0, 10.0), "b": (-5.0, 5.0), "c": (1.0, 3.0)}
OPTIMUM = {"a": 7.5, "b": -2.0, "c": 1.5}


def _theta(**values: float) -> Theta:
    merged = {"a": 1.0, "b": 0.0, "c": 2.0}
    merged.update(values)
    return Theta(values=merged, bounds=dict(BOUNDS))


def _quadratic(theta: Theta) -> float:
    """Гладкая цель с одним максимумом внутри границ. Не заглушка:
    оптимизатор считает по ней настоящий поиск, а тест знает ответ."""

    return -sum((theta.values[name] - OPTIMUM[name]) ** 2 for name in OPTIMUM)


def _feasible_result(objective: float) -> OptimizerResult:
    return OptimizerResult(
        objective=objective, feasible=True, violations_by_scenario=(), provenance={}
    )


def _infeasible_result(objective: float, *regrets: float) -> OptimizerResult:
    return OptimizerResult(
        objective=objective,
        feasible=False,
        violations_by_scenario=tuple(
            ScenarioViolation(scenario_id=f"s{i}", regret=regret, what="limit")
            for i, regret in enumerate(regrets)
        ),
        provenance={},
    )


class _Counting:
    """Оборачивает цель и считает вызовы: бюджет проверяется по факту,
    а не по отчёту, который поиск сам о себе печатает."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0
        self.seen: list[Theta] = []

    def __call__(self, theta: Theta) -> OptimizerResult:
        self.calls += 1
        self.seen.append(theta)
        return self._inner(theta)


def _nominal_objective(nominal=_quadratic, battery=()) -> Objective:
    return Objective(nominal=nominal, battery=battery, provenance=lambda theta: {})


# --- 1. Подключается к границе задачи 37 -----------------------------------


def test_optimizer_drives_the_task_37_objective_and_improves_it() -> None:
    """Поиск идёт через `Objective` §6.1 — не через собственный интерфейс —
    и приходит к оптимуму заметно ближе, чем стартовая точка."""

    counting = _Counting(_nominal_objective())
    start = _theta()
    report = optimize(counting, start, seed=42, max_evaluations=600)

    assert isinstance(report, SearchReport)
    assert isinstance(report.best, Evaluation)
    assert report.best.result.objective > _quadratic(start)

    for name, target in OPTIMUM.items():
        assert abs(report.best.theta.values[name] - target) < 1e-3, name


def test_returned_best_carries_the_full_optimizer_result() -> None:
    """Наружу отдаётся не скаляр: `feasible`, `violations_by_scenario` и
    `provenance` доезжают до вызывающей стороны нетронутыми."""

    stamp = {"surrogate": "a" * 64, "groups": "b" * 64, "dataset": "c" * 64, "seed": "7"}
    objective = Objective(
        nominal=_quadratic,
        battery=(),
        provenance=lambda theta: dict(stamp),
    )
    report = optimize(objective, _theta(), seed=7, max_evaluations=40)

    assert isinstance(report.best.result, OptimizerResult)
    assert report.best.result.provenance == stamp
    assert report.best.result.violations_by_scenario == ()


# --- 2. Ограничение не сворачивается в штраф -------------------------------


def test_infeasible_never_beats_feasible_however_large_the_objective() -> None:
    """Ключевое свойство §13.3. Недопустимая точка с ЧДД на два порядка выше
    обязана проиграть допустимой — иначе устойчивость стала бы штрафом,
    который допустимо «выкупить» достаточно большим номиналом."""

    modest_but_feasible = _feasible_result(1.0)
    enormous_but_infeasible = _infeasible_result(1.0e15, 1.0e-9)

    assert is_better(modest_but_feasible, enormous_but_infeasible)
    assert not is_better(enormous_but_infeasible, modest_but_feasible)


def test_search_prefers_the_feasible_region_over_a_higher_infeasible_peak() -> None:
    """То же свойство, но у работающего поиска, а не у функции сравнения:
    цель устроена так, что максимум номинала лежит в недопустимой зоне."""

    def nominal(theta: Theta) -> float:
        return theta.values["a"]  # растёт до правой границы

    class _CapScenario:
        scenario_id = "cap"

        def __call__(self, theta: Theta) -> ScenarioOutcome:
            excess = theta.values["a"] - 4.0
            if excess <= 0.0:
                return ScenarioOutcome(regret=0.0, feasible=True, what="")
            return ScenarioOutcome(regret=excess, feasible=False, what="a > 4")

    objective = Objective(nominal=nominal, battery=(_CapScenario(),), provenance=lambda t: {})
    report = optimize(objective, _theta(a=1.0), seed=3, max_evaluations=400)

    assert report.best.result.feasible is True
    assert report.best.theta.values["a"] <= 4.0
    # И при этом внутри допустимой области он всё же максимизирует номинал.
    assert report.best.theta.values["a"] > 3.9


def test_objective_of_the_best_is_the_nominal_value_untouched_by_regret() -> None:
    """`objective` лучшей точки — ровно то, что вернул номинальный сценарий.
    Никакой поправки на батарею в него не подмешано."""

    class _AlwaysViolating:
        scenario_id = "always"

        def __call__(self, theta: Theta) -> ScenarioOutcome:
            return ScenarioOutcome(regret=1.0e12, feasible=False, what="всегда")

    objective = Objective(
        nominal=_quadratic, battery=(_AlwaysViolating(),), provenance=lambda t: {}
    )
    report = optimize(objective, _theta(), seed=11, max_evaluations=200)

    assert report.best.result.objective == pytest.approx(_quadratic(report.best.theta))
    assert report.best.result.feasible is False


# --- 3. Сложения по батарее нет --------------------------------------------


def test_ranking_of_infeasible_points_never_sums_the_battery() -> None:
    """Две недопустимые точки: у одной одно нарушение с regret 100, у другой
    два по 1. Сумма сказала бы, что вторая лучше (2 < 100). Правило §6.1 —
    сначала число нарушенных сценариев — говорит обратное, и это не деталь
    реализации: сложение по батарее запрещено (`optimizer/interface.py`)."""

    one_big = _infeasible_result(0.0, 100.0)
    two_small = _infeasible_result(0.0, 1.0, 1.0)

    assert is_better(one_big, two_small)
    assert not is_better(two_small, one_big)


def test_among_equally_many_violations_the_worst_scenario_decides() -> None:
    """При равном числе нарушений сравнивает худший сценарий — `max`, не `sum`.
    Суммы 10+10 и 19+1 равны, максимумы 10 и 19 — нет."""

    balanced = _infeasible_result(0.0, 10.0, 10.0)
    skewed = _infeasible_result(0.0, 19.0, 1.0)

    assert is_better(balanced, skewed)


def test_search_module_contains_no_summation_over_the_battery() -> None:
    """Статическая проверка: `violations_by_scenario` в коде поиска не
    попадает под `sum(...)`. Запрет структурный, а не «мы помним»."""

    path = Path(__file__).resolve().parents[1].joinpath("search.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "sum":
            continue
        source = ast.dump(node)
        assert "violations_by_scenario" not in source, "батарея свёрнута сложением"
        assert "regret" not in source, "regret свёрнут сложением"


# --- 4. Границы θ соблюдаются ----------------------------------------------


def test_no_evaluated_theta_ever_leaves_the_declared_bounds() -> None:
    """Проверяется на всей истории, а не на лучшей точке: за границы нельзя
    выходить даже пробно — там `Constraints` физически не определены."""

    counting = _Counting(_nominal_objective())
    report = optimize(counting, _theta(), seed=5, max_evaluations=300)

    assert len(counting.seen) == report.evaluations
    for theta in counting.seen:
        for name, (low, high) in BOUNDS.items():
            assert low <= theta.values[name] <= high, f"{name}={theta.values[name]}"


def test_start_on_the_boundary_stays_inside() -> None:
    """Отражение от стенок, а не обрезка: старт в самом углу куба не выносит
    поиск наружу и не приклеивает всё облако к границе."""

    corner = Theta(values={"a": 0.0, "b": -5.0, "c": 1.0}, bounds=dict(BOUNDS))
    counting = _Counting(_nominal_objective())
    optimize(counting, corner, seed=9, max_evaluations=120)

    for theta in counting.seen:
        for name, (low, high) in BOUNDS.items():
            assert low <= theta.values[name] <= high, f"{name}={theta.values[name]}"

    distinct = {round(theta.values["a"], 9) for theta in counting.seen}
    assert len(distinct) > 1, "все точки слиплись на границе"


def test_bounds_are_carried_into_every_produced_theta() -> None:
    """θ на выходе несёт те же объявленные границы: без них следующий
    потребитель не сможет проверить, что она допустима."""

    counting = _Counting(_nominal_objective())
    optimize(counting, _theta(), seed=1, max_evaluations=40)

    for theta in counting.seen:
        assert theta.bounds == BOUNDS


# --- 5. Воспроизводимость по seed ------------------------------------------


def test_same_seed_gives_the_same_trajectory() -> None:
    """Сдача требует зафиксированного seed без неконтролируемых случайных
    параметров (`config/schema.py`). Один seed — одна и та же история."""

    first = _Counting(_nominal_objective())
    second = _Counting(_nominal_objective())
    optimize(first, _theta(), seed=2024, max_evaluations=200)
    optimize(second, _theta(), seed=2024, max_evaluations=200)

    assert [theta.values for theta in first.seen] == [theta.values for theta in second.seen]


def test_different_seed_gives_a_different_trajectory() -> None:
    first = _Counting(_nominal_objective())
    second = _Counting(_nominal_objective())
    optimize(first, _theta(), seed=1, max_evaluations=200)
    optimize(second, _theta(), seed=2, max_evaluations=200)

    assert [theta.values for theta in first.seen] != [theta.values for theta in second.seen]


def test_seed_comes_from_the_component_registry() -> None:
    """`optimizer` заявлен в реестре компонентов конфига — seed берётся
    оттуда, а не назначается на месте."""

    from aios_backend.domain.configuration.schema import COMPONENT_SEEDS

    assert "optimizer" in COMPONENT_SEEDS


# --- 6. Бюджет оценок жёсткий ----------------------------------------------


def test_budget_is_never_exceeded() -> None:
    """Вызов границы стоит прогона (513 с на реальном OPM), поэтому бюджет
    считается оценками и превышаться не может."""

    for budget in (12, 40, 137, 500):
        counting = _Counting(_nominal_objective())
        report = optimize(counting, _theta(), seed=17, max_evaluations=budget)
        assert counting.calls <= budget, budget
        assert report.evaluations == counting.calls


def test_partial_generation_is_not_started() -> None:
    """Поколение оценивается целиком либо не начинается: половина поколения
    даёт смещённую рекомбинацию, а стоит столько же, сколько лишние прогоны."""

    size = 3
    population = default_population(size)
    counting = _Counting(_nominal_objective())
    report = optimize(
        counting, _theta(), seed=4, max_evaluations=population * 3 + population - 1
    )

    assert counting.calls % population == 0
    assert report.generations == counting.calls // population


def test_budget_smaller_than_one_generation_is_an_error_not_an_empty_answer() -> None:
    """Моков нет: если бюджета не хватает даже на одно поколение, поиск
    обязан сказать это исключением, а не вернуть стартовую θ как «лучшую»."""

    with pytest.raises(OptimizerError):
        optimize(_nominal_objective(), _theta(), seed=1, max_evaluations=2)


def test_history_is_kept_whole_and_in_evaluation_order() -> None:
    """История — сдаваемая трасса выбора кандидата (§10.1), не диагностика."""

    counting = _Counting(_nominal_objective())
    report = optimize(counting, _theta(), seed=8, max_evaluations=100)

    assert len(report.history) == counting.calls
    assert [item.theta.values for item in report.history] == [
        theta.values for theta in counting.seen
    ]
    assert report.best in report.history


# --- 7. Слепота к скважинам и расписанию -----------------------------------


def test_search_module_never_references_well_level_types() -> None:
    """Та же статическая проверка, что у задачи 37: оптимизатор двигает
    ≤10 чисел и не знает ни фонда, ни расписания."""

    path = Path(__file__).resolve().parents[1].joinpath("search.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)

    for forbidden in ("Schedule", "FieldState", "Well", "ControlEvent", "IntervalResponse"):
        assert forbidden not in names, f"{forbidden!r} просочился в оптимизатор"


def test_objective_function_protocol_is_theta_to_optimizer_result() -> None:
    hints = get_type_hints(optimize)
    assert hints["start"] is Theta
    assert hints["return"] is SearchReport

    signature = inspect.signature(optimize)
    assert list(signature.parameters)[:2] == ["objective", "start"]


# --- Отказы вместо правдоподобных чисел ------------------------------------


def test_degenerate_bounds_are_rejected() -> None:
    degenerate = Theta(values={"a": 1.0}, bounds={"a": (2.0, 2.0)})
    with pytest.raises(OptimizerError):
        optimize(_nominal_objective(lambda theta: 0.0), degenerate, seed=1, max_evaluations=50)


def test_non_finite_bounds_are_rejected() -> None:
    unbounded = Theta(values={"a": 1.0}, bounds={"a": (0.0, math.inf)})
    with pytest.raises(OptimizerError):
        optimize(_nominal_objective(lambda theta: 0.0), unbounded, seed=1, max_evaluations=50)


def test_theta_without_parameters_is_rejected() -> None:
    empty = Theta(values={}, bounds={})
    with pytest.raises(OptimizerError):
        optimize(_nominal_objective(lambda theta: 0.0), empty, seed=1, max_evaluations=50)


def test_zero_budget_is_rejected() -> None:
    with pytest.raises(OptimizerError):
        optimize(_nominal_objective(), _theta(), seed=1, max_evaluations=0)


def test_ten_parameters_are_supported() -> None:
    """Потолок θ — 10 (`MAX_THETA_PARAMS`); на нём поиск обязан работать,
    а не упираться в размерность ковариации."""

    names = [f"p{i}" for i in range(10)]
    target = {name: 0.25 * (i + 1) for i, name in enumerate(names)}
    theta = Theta(
        values={name: 0.0 for name in names},
        bounds={name: (-3.0, 3.0) for name in names},
    )

    def nominal(candidate: Theta) -> float:
        return -sum((candidate.values[name] - target[name]) ** 2 for name in names)

    report = optimize(_nominal_objective(nominal), theta, seed=6, max_evaluations=3000)
    assert report.best.result.objective > nominal(theta)
    for name in names:
        assert abs(report.best.theta.values[name] - target[name]) < 0.05, name


def test_stop_reason_is_always_reported() -> None:
    report = optimize(_nominal_objective(), _theta(), seed=13, max_evaluations=2000)
    assert report.stop_reason
    assert report.generations >= 1
