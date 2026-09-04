"""Шлюз проекции: ни одна уставка не попадает в расписание мимо неё.

Протокол §5.2 плана: агенты предлагают, проекция отсекает, OPM решает.
Часть проверок читает исходник `schedule_search.py` — единственность точки
входа в расписание нельзя доказать одним прогоном, её надо доказать тем,
что другой записи в `pending` в файле просто нет.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.core.contracts import MAX_LRAT_M3_PER_DAY, ControlEvent, EventKind

from backend.domain.policy.agents.projection import (
    RATE_KINDS,
    HardConstraints,
    project_to_hard_constraints,
)

SEARCH_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "application"
    / "optimization"
    / "schedule_search.py"
)
GATE = "_admit"


def counting_projection(counter: list[ControlEvent]):
    def projection(
        event: ControlEvent, constraints: HardConstraints
    ) -> ControlEvent:
        counter.append(event)
        return project_to_hard_constraints(event, constraints)

    return projection


def test_the_source_of_the_search_is_where_the_test_expects_it() -> None:
    assert SEARCH_SOURCE.is_file(), SEARCH_SOURCE


def _pending_writes(tree: ast.Module) -> list[tuple[str, int]]:
    writes: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            value = target.value
            if isinstance(value, ast.Name) and value.id == "pending":
                writes.append((ast.unparse(target), node.lineno))
    return writes


def _enclosing_function(tree: ast.Module, lineno: int) -> str:
    name = "<module>"
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= lineno <= end:
            name = node.name
    return name


def _substitutable_names(tree: ast.Module, name: str) -> set[str]:
    """Имена, которые вызывающий может подменить: свои и захваченные извне."""

    chain: list[ast.FunctionDef] = []
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= target.lineno <= end:
            chain.append(node)
    names: set[str] = set()
    for node in chain:
        names.update(
            argument.arg
            for argument in node.args.args + node.args.kwonlyargs
        )
    return names


def test_only_the_gate_writes_a_setpoint_into_the_schedule() -> None:
    tree = ast.parse(SEARCH_SOURCE.read_text(encoding="utf-8"))
    outside = [
        (expression, lineno)
        for expression, lineno in _pending_writes(tree)
        if _enclosing_function(tree, lineno) != GATE
    ]
    assert not outside, (
        f"запись в расписание мимо {GATE}: {outside} — уставка обошла "
        f"проекцию на жёсткие ограничения"
    )


def test_the_gate_passes_every_event_through_the_projection() -> None:
    tree = ast.parse(SEARCH_SOURCE.read_text(encoding="utf-8"))
    gate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == GATE
    )
    calls = {
        node.func.id
        for node in ast.walk(gate)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "projection" in calls


def test_every_writer_of_the_schedule_takes_a_projection() -> None:
    tree = ast.parse(SEARCH_SOURCE.read_text(encoding="utf-8"))
    callers = {
        _enclosing_function(tree, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == GATE
    }
    callers.discard(GATE)
    assert callers
    for caller in sorted(callers):
        assert "projection" in _substitutable_names(tree, caller), (
            f"{caller} пишет в расписание, но проекцию подменить нельзя: "
            f"шлюз не проверяем"
        )


def test_the_projection_holds_the_physical_cap_of_a_well() -> None:
    constraints = HardConstraints(well_cap_m3_per_day={"i1": 100.0})
    event = ControlEvent(
        control_step=0, well="i1", kind=EventKind.SET_RATE, value=250.0
    )
    assert project_to_hard_constraints(event, constraints).value == 100.0


def test_the_projection_leaves_an_admissible_setpoint_untouched() -> None:
    constraints = HardConstraints(well_cap_m3_per_day={"i1": 100.0})
    event = ControlEvent(
        control_step=0, well="i1", kind=EventKind.SET_RATE, value=80.0
    )
    assert project_to_hard_constraints(event, constraints) is event


def test_a_well_without_a_declared_cap_is_not_cut() -> None:
    constraints = HardConstraints(well_cap_m3_per_day={})
    event = ControlEvent(
        control_step=0, well="i9", kind=EventKind.SET_RATE, value=9999.0
    )
    assert project_to_hard_constraints(event, constraints) is event


def test_the_projection_holds_the_lrat_ceiling_of_the_methodology() -> None:
    constraints = HardConstraints(well_cap_m3_per_day={})
    event = ControlEvent(
        control_step=0,
        well="p1",
        kind=EventKind.SET_LRAT,
        value=MAX_LRAT_M3_PER_DAY,
    )
    projected = project_to_hard_constraints(
        event, HardConstraints(well_cap_m3_per_day={}, lrat_ceiling_m3_per_day=50.0)
    )
    assert projected.value == 50.0
    assert project_to_hard_constraints(event, constraints) is event


def test_a_status_event_carries_no_setpoint_and_passes_unchanged() -> None:
    constraints = HardConstraints(well_cap_m3_per_day={"i1": 1.0})
    for kind in (EventKind.OPEN, EventKind.SHUT, EventKind.CONVERT_INJ):
        event = ControlEvent(control_step=0, well="i1", kind=kind)
        assert project_to_hard_constraints(event, constraints) is event
    assert set(RATE_KINDS) == {EventKind.SET_LRAT, EventKind.SET_RATE}


def test_a_negative_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="отрицательный потолок"):
        HardConstraints(well_cap_m3_per_day={"i1": -1.0})


def test_a_non_positive_ceiling_is_refused() -> None:
    with pytest.raises(ValueError, match="не положителен"):
        HardConstraints(well_cap_m3_per_day={}, lrat_ceiling_m3_per_day=0.0)


def test_a_detector_projection_sees_every_event_of_the_dense_layer() -> None:
    search = pytest.importorskip(
        "backend.application.optimization.schedule_search",
        reason="сквозной поиск требует torch (extras ml)",
    )
    _scale_step_injection_to_limit = search._scale_step_injection_to_limit
    seen: list[ControlEvent] = []
    pending = {
        (0, "i1", EventKind.SET_RATE): ControlEvent(
            control_step=0, well="i1", kind=EventKind.SET_RATE, value=80.0
        ),
        (0, "i2", EventKind.SET_RATE): ControlEvent(
            control_step=0, well="i2", kind=EventKind.SET_RATE, value=20.0
        ),
    }
    total = _scale_step_injection_to_limit(
        pending,
        0,
        50.0,
        current_is_open={"i1": True, "i2": True},
        current_setpoint={"i1": 80.0, "i2": 20.0},
        projection=counting_projection(seen),
    )
    assert total == pytest.approx(50.0)
    assert {event.well for event in seen} == {"i1", "i2"}
    for key, event in pending.items():
        if key[2] not in RATE_KINDS:
            continue
        assert any(
            candidate.well == event.well and candidate.kind == event.kind
            for candidate in seen
        )
