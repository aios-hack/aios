"""Приёмка задачи 37 (docs/v1/assignments/andrey.md, docs/context/08_contracts.md §6.1):

- оптимизатор не видит ни скважин, ни расписания;
- ограничение устойчивости не сворачивается в штраф.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

from aios_backend.core.contracts import OptimizerResult, Theta
from aios_backend.application.optimization import Objective, ScenarioOutcome


def _theta(value: float = 0.5) -> Theta:
    return Theta(values={"x": value}, bounds={"x": (0.0, 1.0)})


class _FixedScenario:
    def __init__(self, scenario_id: str, outcome: ScenarioOutcome) -> None:
        self.scenario_id = scenario_id
        self._outcome = outcome

    def __call__(self, theta: Theta) -> ScenarioOutcome:
        return self._outcome


def test_objective_signature_is_exactly_theta_to_optimizer_result() -> None:
    """Единственная граница: вход `Theta`, выход `OptimizerResult` — ничего
    из Schedule/well/FieldState в сигнатуре появиться не может."""

    signature = inspect.signature(Objective.__call__)
    params = [name for name in signature.parameters if name != "self"]
    assert params == ["theta"]

    hints = get_type_hints(Objective.__call__)
    assert hints["theta"] is Theta
    assert hints["return"] is OptimizerResult


def test_interface_module_never_references_well_level_types() -> None:
    """Статическая проверка слепоты: код (не проза докстрок и комментариев,
    которые вправе цитировать контракт §6.1 целиком) не импортирует и не
    использует Schedule/FieldState/well."""

    import ast

    path = Path(__file__).resolve().parents[1].joinpath("interface.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg) and node.annotation is not None:
            names.add(node.arg)

    for forbidden in ("Schedule", "FieldState", "well", "Well"):
        assert forbidden not in names, f"{forbidden!r} просочился в код интерфейса оптимизатора"


def test_scenario_violation_does_not_move_objective() -> None:
    """Даже катастрофическая просадка на сценарии не трогает `objective` —
    иначе ограничение устойчивости стало бы штрафом за пределами номинала."""

    nominal_value = 1.0e11

    def nominal(theta: Theta) -> float:
        return nominal_value

    catastrophic = _FixedScenario(
        "water_cut_2015",
        ScenarioOutcome(regret=9.9e12, feasible=False, what="обводнённость > лимита"),
    )

    objective = Objective(nominal=nominal, battery=(catastrophic,), provenance=lambda theta: {})
    result = objective(_theta())

    assert result.objective == nominal_value
    assert result.feasible is False
    assert len(result.violations_by_scenario) == 1
    violation = result.violations_by_scenario[0]
    assert violation.scenario_id == "water_cut_2015"
    assert violation.regret == 9.9e12
    assert violation.what == "обводнённость > лимита"


def test_feasible_true_when_every_scenario_feasible() -> None:
    def nominal(theta: Theta) -> float:
        return 5.0e10

    clean = _FixedScenario("holdout_1", ScenarioOutcome(regret=0.0, feasible=True, what=""))

    objective = Objective(nominal=nominal, battery=(clean,), provenance=lambda theta: {})
    result = objective(_theta())

    assert result.feasible is True
    assert result.violations_by_scenario == ()


def test_only_infeasible_scenarios_are_reported() -> None:
    """Нарушивший сценарий виден по имени, выполнивший — не засоряет список."""

    def nominal(theta: Theta) -> float:
        return 1.0

    ok = _FixedScenario("dev_1", ScenarioOutcome(regret=0.0, feasible=True, what=""))
    bad = _FixedScenario("dev_2", ScenarioOutcome(regret=3.0, feasible=False, what="limit"))

    objective = Objective(nominal=nominal, battery=(ok, bad), provenance=lambda theta: {})
    result = objective(_theta())

    assert [violation.scenario_id for violation in result.violations_by_scenario] == ["dev_2"]


def test_duplicate_scenario_ids_are_rejected() -> None:
    scenario_a = _FixedScenario("s", ScenarioOutcome(regret=0.0, feasible=True, what=""))
    scenario_b = _FixedScenario("s", ScenarioOutcome(regret=0.0, feasible=True, what=""))

    with pytest.raises(ValueError):
        Objective(nominal=lambda theta: 0.0, battery=(scenario_a, scenario_b), provenance=lambda theta: {})


def test_provenance_is_passed_through_unchanged() -> None:
    stamp = {"surrogate": "a" * 64, "groups": "b" * 64, "dataset": "c" * 64, "seed": "42"}

    objective = Objective(nominal=lambda theta: 0.0, battery=(), provenance=lambda theta: dict(stamp))
    result = objective(_theta())

    assert result.provenance == stamp


def test_theta_is_the_only_thing_every_component_receives() -> None:
    """Ни номинал, ни сценарий, ни provenance не получают ничего, кроме θ —
    проверяем сигнатуры внедрённых компонентов, а не только доверяем аннотации."""

    seen: list[Theta] = []

    def nominal(theta: Theta) -> float:
        seen.append(theta)
        assert isinstance(theta, Theta)
        return 0.0

    scenario = _FixedScenario("s", ScenarioOutcome(regret=0.0, feasible=True, what=""))

    def provenance(theta: Theta) -> dict[str, str]:
        assert isinstance(theta, Theta)
        return {}

    objective = Objective(nominal=nominal, battery=(scenario,), provenance=provenance)
    theta = _theta(0.7)
    objective(theta)

    assert seen == [theta]
