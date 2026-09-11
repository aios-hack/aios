from __future__ import annotations

import ast
import math
import sys
import types
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import pytest

from backend.core.contracts import (
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.contexts.constraints.domain.constraints import (
    DEFAULT_WATER_SAFETY_FACTOR,
    WATER_SAFETY_FACTOR,
    water_safety_factor,
)
from backend.contexts.constraints.domain.constraints import water_supply_policy
from backend.contexts.schedule.domain.canonical import canonicalize
from backend.contexts.optimization.application import environment as _environment
from backend.contexts.optimization.application import search_use_case as _search_use_case
from backend.contexts.optimization.application import water_baseline_run as _water_baseline_run

SEARCH_SOURCE = Path(_environment.__file__)
RUN_SOURCE = Path(_search_use_case.__file__)
BASELINE_SOURCE = Path(_water_baseline_run.__file__)

_BUDGET_NAMES = (
    "InjectionBudget",
    "injection_budget_for_step",
    "_field_limit_for_step",
    "_damped_value",
    "_relax_rate_layer",
    "_scale_step_injection_to_limit",
    "ScheduleSearchError",
)

_BUDGET_CONSTANTS = (
    "SOURCE_PHYSICAL_HEADROOM",
    "SOURCE_CASE_INJECTION_LIMIT",
    "SOURCE_WATER_BALANCE",
    "SOURCE_COMMAND_MARGIN",
    "SOURCE_WATER_BALANCE_REPAIR",
    "UNCONSTRAINED_BUDGET_M3_PER_DAY",
    "SETPOINT_STEP_M3_PER_DAY",
    "DAMPER_STEP_FRACTION",
    "WATER_COMMAND_SAFETY_FACTOR",
    "UNCONSTRAINED_WELLS",
)


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function_def(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"функция {name} не найдена")


def _identity_projection(event: ControlEvent, hard: Any) -> ControlEvent:
    return event


def _budget_namespace() -> dict[str, Any]:
    module = _module_ast(SEARCH_SOURCE)
    wanted = set(_BUDGET_NAMES)
    constants = set(_BUDGET_CONSTANTS)
    body: list[ast.stmt] = []
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted:
            body.append(node)
        elif isinstance(node, ast.Assign):
            targets = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if targets & constants:
                body.append(node)
    found = {
        node.name
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert found == wanted, f"не найдено: {sorted(wanted - found)}"
    holder = types.ModuleType("budget_under_test")
    sys.modules["budget_under_test"] = holder
    namespace: dict[str, Any] = holder.__dict__
    namespace.update({
        "__name__": "budget_under_test",
        "annotations": __import__("__future__").annotations,
        "math": math,
        "dataclass": dataclass,
        "replace": replace,
        "canonicalize": canonicalize,
        "Constraints": Constraints,
        "ControlEvent": ControlEvent,
        "EventKind": EventKind,
        "Schedule": Schedule,
        "Sequence": Sequence,
        "HardConstraints": dict,
        "project_to_hard_constraints": _identity_projection,
        "Projection": object,
        "water_supply_policy": water_supply_policy,
    })
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(SEARCH_SOURCE), "exec"),
        namespace,
    )
    return namespace


BUDGET = _budget_namespace()


def _schedule(events: tuple[ControlEvent, ...]) -> Schedule:
    wells = tuple(sorted({event.well for event in events})) or ("I1",)
    return Schedule(
        meta=ScheduleMeta(wells=wells, provenance="test"),
        initial_state={
            well: WellState(
                availability=Availability.AVAILABLE,
                role=Role.INJ,
                operating_status=OperatingStatus.OPEN,
                setpoint=0.0,
            )
            for well in wells
        },
        fixed_deck_events=(),
        control_events=events,
    )


def test_no_case_constraints_means_no_ceiling_at_all() -> None:
    budget = BUDGET["injection_budget_for_step"](
        control_step=0,
        constraints=Constraints(),
        year=2007,
        produced_water_by_step=[40.0],
    )

    assert budget.unconstrained
    assert budget.limit_m3_per_day == BUDGET["UNCONSTRAINED_BUDGET_M3_PER_DAY"]
    assert budget.binding_source == "none"
    assert budget.contributions == ()


def test_unconstrained_budget_does_not_scale_the_injection_layer() -> None:
    pending = {
        (0, "I1", EventKind.SET_RATE): ControlEvent(0, "I1", EventKind.SET_RATE, 900.0),
        (0, "I2", EventKind.SET_RATE): ControlEvent(0, "I2", EventKind.SET_RATE, 700.0),
    }

    total = BUDGET["_scale_step_injection_to_limit"](
        pending,
        0,
        BUDGET["UNCONSTRAINED_BUDGET_M3_PER_DAY"],
        current_is_open={"I1": True, "I2": True},
        current_setpoint={"I1": 900.0, "I2": 700.0},
    )

    assert total == pytest.approx(1600.0)
    assert pending[(0, "I1", EventKind.SET_RATE)].value == pytest.approx(900.0)
    assert pending[(0, "I2", EventKind.SET_RATE)].value == pytest.approx(700.0)


def test_budget_takes_the_minimum_and_names_the_winner() -> None:
    constraints = Constraints(
        injection_limits={2007: 50.0},
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "external_water_m3_per_day": 5.0,
        },
    )

    budget = BUDGET["injection_budget_for_step"](
        control_step=0,
        constraints=constraints,
        year=2007,
        produced_water_by_step=[40.0],
        physical_limit_m3_per_day=100.0,
    )

    assert budget.limit_m3_per_day == pytest.approx(45.0)
    assert budget.binding_source == BUDGET["SOURCE_WATER_BALANCE"]
    assert dict(budget.contributions) == pytest.approx(
        {
            BUDGET["SOURCE_PHYSICAL_HEADROOM"]: 100.0,
            BUDGET["SOURCE_CASE_INJECTION_LIMIT"]: 50.0,
            BUDGET["SOURCE_WATER_BALANCE"]: 45.0,
        }
    )


def test_case_limit_can_win_over_the_water_balance() -> None:
    constraints = Constraints(
        injection_limits={2007: 20.0},
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "external_water_m3_per_day": 5.0,
        },
    )

    budget = BUDGET["injection_budget_for_step"](
        control_step=0,
        constraints=constraints,
        year=2007,
        produced_water_by_step=[40.0],
        physical_limit_m3_per_day=100.0,
    )

    assert budget.limit_m3_per_day == pytest.approx(20.0)
    assert budget.binding_source == BUDGET["SOURCE_CASE_INJECTION_LIMIT"]


def test_command_margin_is_a_named_separate_contribution() -> None:
    constraints = Constraints(
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "external_water_m3_per_day": 0.0,
        }
    )

    budget = BUDGET["injection_budget_for_step"](
        control_step=0,
        constraints=constraints,
        year=2007,
        produced_water_by_step=[100.0],
        physical_limit_m3_per_day=1000.0,
        command_margin=BUDGET["WATER_COMMAND_SAFETY_FACTOR"],
    )

    contributions = dict(budget.contributions)
    assert contributions[BUDGET["SOURCE_WATER_BALANCE"]] == pytest.approx(100.0)
    assert budget.limit_m3_per_day == pytest.approx(95.0)
    assert budget.binding_source == BUDGET["SOURCE_COMMAND_MARGIN"]
    assert contributions[BUDGET["SOURCE_COMMAND_MARGIN"]] == pytest.approx(95.0)


def test_margin_of_one_leaves_the_budget_untouched() -> None:
    constraints = Constraints(injection_limits={2007: 50.0})

    budget = BUDGET["injection_budget_for_step"](
        control_step=0,
        constraints=constraints,
        year=2007,
        produced_water_by_step=[],
        physical_limit_m3_per_day=100.0,
        command_margin=1.0,
    )

    assert budget.limit_m3_per_day == pytest.approx(50.0)
    assert budget.binding_source == BUDGET["SOURCE_CASE_INJECTION_LIMIT"]
    assert BUDGET["SOURCE_COMMAND_MARGIN"] not in dict(budget.contributions)


def test_nonsense_margin_is_refused_instead_of_silently_clamped() -> None:
    with pytest.raises(BUDGET["ScheduleSearchError"]):
        BUDGET["injection_budget_for_step"](
            control_step=3,
            constraints=Constraints(injection_limits={2007: 50.0}),
            year=2007,
            produced_water_by_step=[],
            physical_limit_m3_per_day=100.0,
            command_margin=0.0,
        )


def test_budget_is_serialisable_into_the_trace() -> None:
    budget = BUDGET["injection_budget_for_step"](
        control_step=7,
        constraints=Constraints(injection_limits={2007: 50.0}),
        year=2007,
        produced_water_by_step=[],
        physical_limit_m3_per_day=100.0,
    )
    entry = budget.as_trace_entry()

    assert entry["control_step"] == 7
    assert entry["binding_source"] == BUDGET["SOURCE_CASE_INJECTION_LIMIT"]
    assert entry["limit_m3_per_day"] == pytest.approx(50.0)
    assert entry["contributions"][BUDGET["SOURCE_PHYSICAL_HEADROOM"]] == pytest.approx(
        100.0
    )


def test_old_field_limit_helper_still_returns_the_same_number() -> None:
    constraints = Constraints(
        injection_limits={2007: 50.0},
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "external_water_m3_per_day": 5.0,
        },
    )

    assert BUDGET["_field_limit_for_step"](
        physical_limit_m3_per_day=100.0,
        constraints=constraints,
        year=2007,
        control_step=0,
        produced_water_by_step=[40.0],
    ) == pytest.approx(45.0)


def test_policy_records_the_budget_decision_in_the_trace_sink() -> None:
    source = ast.unparse(_function_def(_module_ast(SEARCH_SOURCE), "make_policy"))

    assert "injection_budget_for_step(" in source
    assert "budget_entries.append(budget)" in source
    assert "trace_sink['injection_budget']" in source
    assert "budget.binding_source" in source


def test_policy_has_exactly_one_place_computing_the_ceiling() -> None:
    source = SEARCH_SOURCE.read_text(encoding="utf-8")

    assert source.count("def injection_budget_for_step(") == 1
    assert source.count("injection_budget_for_step(") == 3
    assert "step_field_limit *= WATER_COMMAND_SAFETY_FACTOR" not in source


def test_damper_moves_up_towards_a_higher_proposal() -> None:
    previous = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 100.0),))
    proposed = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 200.0),))

    relaxed = BUDGET["_relax_rate_layer"](previous, proposed)
    value = next(
        float(event.value or 0.0)
        for event in relaxed.control_events
        if event.kind is EventKind.SET_RATE
    )

    assert value == pytest.approx(150.0)
    assert value > 100.0


def test_damper_still_moves_down_towards_a_lower_proposal() -> None:
    previous = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 200.0),))
    proposed = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 100.0),))

    relaxed = BUDGET["_relax_rate_layer"](previous, proposed)
    value = next(
        float(event.value or 0.0)
        for event in relaxed.control_events
        if event.kind is EventKind.SET_RATE
    )

    assert value == pytest.approx(150.0)
    assert value < 200.0


def test_asymmetric_damper_is_still_reachable_by_flag() -> None:
    previous = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 100.0),))
    proposed = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 200.0),))

    relaxed = BUDGET["_relax_rate_layer"](previous, proposed, symmetric=False)
    value = next(
        float(event.value or 0.0)
        for event in relaxed.control_events
        if event.kind is EventKind.SET_RATE
    )

    assert value == pytest.approx(100.0)


def test_damper_never_produces_a_ratchet_over_repeated_rounds() -> None:
    current = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 100.0),))
    target = _schedule((ControlEvent(0, "I1", EventKind.SET_RATE, 400.0),))
    for _ in range(8):
        current = BUDGET["_relax_rate_layer"](current, target)
    value = next(
        float(event.value or 0.0)
        for event in current.control_events
        if event.kind is EventKind.SET_RATE
    )

    assert value > 350.0


def test_policy_exposes_the_damper_switch() -> None:
    source = ast.unparse(_function_def(_module_ast(SEARCH_SOURCE), "make_policy"))

    assert "symmetric_damper" in source
    assert "symmetric=symmetric_damper" in source


def test_water_safety_factor_defaults_to_one() -> None:
    assert DEFAULT_WATER_SAFETY_FACTOR == 1.0
    assert water_safety_factor(Constraints()) == 1.0


def test_water_safety_factor_from_the_case_is_applied() -> None:
    constraints = Constraints(infrastructure={WATER_SAFETY_FACTOR: 0.85})

    assert water_safety_factor(constraints) == pytest.approx(0.85)


def test_water_safety_factor_out_of_range_is_refused() -> None:
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            water_safety_factor(Constraints(infrastructure={WATER_SAFETY_FACTOR: bad}))


def test_baseline_run_no_longer_hardcodes_the_undeclared_margin() -> None:
    source = BASELINE_SOURCE.read_text(encoding="utf-8")

    assert "WATER_SAFETY_FACTOR = 0.85" not in source
    assert "WATER_SAFETY_FACTOR = DEFAULT_WATER_SAFETY_FACTOR" in source
    assert "case_water_safety_factor(constraints)" in source


def test_baseline_run_marks_where_the_factor_came_from() -> None:
    source = ast.unparse(_function_def(_module_ast(BASELINE_SOURCE), "main"))

    assert "water_safety_factor_source" in source
    assert "case_water_safety_factor" in source


def test_repair_margins_are_named_constants_not_literals() -> None:
    source = RUN_SOURCE.read_text(encoding="utf-8")

    assert "WATER_REPAIR_MARGIN = 0.98" in source
    assert "WATER_REPAIR_CEILING = 0.95" in source
    assert "min(0.95, 0.98 * available / actual)" not in source


def test_repair_reports_its_own_contribution_to_the_trace() -> None:
    source = ast.unparse(
        _function_def(_module_ast(RUN_SOURCE), "_repair_predicted_water_balance")
    )

    assert "budget_trace" in source
    assert "SOURCE_WATER_BALANCE_REPAIR" in source
    assert "WATER_REPAIR_MARGIN" in source
    assert "WATER_REPAIR_CEILING" in source
