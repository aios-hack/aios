from __future__ import annotations

from types import MappingProxyType

import pytest

from backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.domain.configuration.schema import DEFAULT_BUDGETS
from backend.domain.policy import Evaluation, resolve
from backend.domain.policy.fixed_point import FixedPointResult, Visited

WELL = "42"


def schedule_with(*values: float) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=(WELL,)),
        initial_state={
            WELL: WellState(
                availability=Availability.AVAILABLE,
                role=Role.PROD,
                operating_status=OperatingStatus.OPEN,
                setpoint=0.0,
            )
        },
        fixed_deck_events=(),
        control_events=tuple(
            ControlEvent(
                control_step=step,
                well=WELL,
                kind=EventKind.SET_LRAT,
                value=value,
            )
            for step, value in enumerate(values)
        ),
    )


def constant_policy(value: float):
    def policy(state: object) -> Schedule:
        return schedule_with(value)

    return policy


def test_evaluation_defaults_are_empty_and_immutable() -> None:
    evaluation = Evaluation(npv=1.0, state=2.0)
    assert evaluation.npv_parts == {}
    assert evaluation.sigma is None
    assert evaluation.physics == {}
    assert evaluation.ood_worst is None
    with pytest.raises(TypeError):
        evaluation.npv_parts["oil"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        evaluation.physics["mass"] = 1  # type: ignore[index]


def test_defaults_are_shared_and_not_per_instance_mutable() -> None:
    first = Evaluation(npv=1.0, state=2.0)
    second = Evaluation(npv=3.0, state=4.0)
    assert first.npv_parts is second.npv_parts
    assert first.physics is second.physics


def test_legacy_positional_construction_still_works() -> None:
    evaluation = Evaluation(5.0, 6.0, 0.25)
    assert evaluation.npv == pytest.approx(5.0)
    assert evaluation.ood_score == pytest.approx(0.25)
    assert evaluation.sigma is None


def test_visited_and_result_defaults_when_evaluation_is_old_style() -> None:
    def evaluator(schedule: Schedule) -> Evaluation:
        return Evaluation(npv=100.0, state=1.0)

    result = resolve(
        policy=constant_policy(1.0),
        evaluator=evaluator,
        initial_state=1.0,
        iteration_cap=DEFAULT_BUDGETS.fixed_point_iteration_cap,
    )
    assert result.converged
    assert result.npv_parts == {}
    assert result.sigma is None
    assert result.physics == {}
    assert result.ood_worst is None
    for entry in result.visited:
        assert entry.npv_parts == {}
        assert entry.sigma is None
        assert entry.physics == {}
        assert entry.ood_worst is None


def test_diagnostics_reach_visited_on_convergence() -> None:
    parts = MappingProxyType({"oil": 120.0, "water": -20.0})
    physics = MappingProxyType({"mass_balance": 2, "bhp_bound": 0})

    def evaluator(schedule: Schedule) -> Evaluation:
        return Evaluation(
            npv=100.0,
            state=1.0,
            ood_score=0.5,
            npv_parts=parts,
            sigma=12.5,
            physics=physics,
            ood_worst="p_res",
        )

    result = resolve(
        policy=constant_policy(1.0),
        evaluator=evaluator,
        initial_state=1.0,
        iteration_cap=DEFAULT_BUDGETS.fixed_point_iteration_cap,
    )
    assert result.visited
    entry = result.visited[0]
    assert entry.npv_parts == {"oil": 120.0, "water": -20.0}
    assert entry.sigma == pytest.approx(12.5)
    assert entry.physics == {"mass_balance": 2, "bhp_bound": 0}
    assert entry.ood_worst == "p_res"
    assert result.npv_parts == entry.npv_parts
    assert result.sigma == pytest.approx(12.5)
    assert result.physics == entry.physics
    assert result.ood_worst == "p_res"
    assert result.best_visited().sigma == pytest.approx(12.5)


def test_diagnostics_reach_visited_on_cap_exhaustion() -> None:
    step = {1.0: 2.0, 2.0: 3.0, 3.0: 1.0}
    sigma_of = {1.0: 1.0, 2.0: 2.0, 3.0: 3.0}
    npv_of = {1.0: 10.0, 2.0: 30.0, 3.0: 20.0}

    def policy(state: object) -> Schedule:
        return schedule_with(float(state))

    def evaluator(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(
            npv=npv_of[current],
            state=step[current],
            sigma=sigma_of[current],
            npv_parts=MappingProxyType({"oil": npv_of[current]}),
            physics=MappingProxyType({"bhp_bound": int(current)}),
            ood_worst=f"well-{current:.0f}",
        )

    result = resolve(
        policy=policy,
        evaluator=evaluator,
        initial_state=1.0,
        iteration_cap=DEFAULT_BUDGETS.fixed_point_iteration_cap,
    )
    assert not result.converged
    assert [entry.sigma for entry in result.visited[:3]] == [1.0, 2.0, 3.0]
    assert result.visited[1].npv_parts == {"oil": 30.0}
    assert result.visited[2].ood_worst == "well-3"
    best = result.best_visited()
    assert best.sigma == pytest.approx(2.0)
    assert result.sigma == pytest.approx(2.0)
    assert result.npv_parts == {"oil": 30.0}
    assert result.physics == {"bhp_bound": 2}
    assert result.ood_worst == "well-2"


def test_visited_and_result_accept_explicit_diagnostics() -> None:
    schedule = schedule_with(1.0)
    visited = Visited(
        iteration=0,
        schedule=schedule,
        schedule_hash="deadbeef",
        npv=5.0,
        npv_parts=MappingProxyType({"oil": 5.0}),
        sigma=0.5,
        physics=MappingProxyType({"mass_balance": 1}),
        ood_worst="q_inj",
    )
    result = FixedPointResult(
        schedule=schedule,
        schedule_hash="deadbeef",
        npv=5.0,
        converged=True,
        self_consistent=True,
        iterations=1,
        visited=(visited,),
        sigma=0.5,
        ood_worst="q_inj",
    )
    assert result.visited[0].physics == {"mass_balance": 1}
    assert result.sigma == pytest.approx(0.5)
    assert result.npv_parts == {}
