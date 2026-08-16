from __future__ import annotations

from dataclasses import dataclass

import pytest

from contracts import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
    hash_schedule,
)

from config.schema import DEFAULT_BUDGETS
from policy import Evaluation, FixedPointResult, resolve
from policy.fixed_point import Visited

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


@dataclass
class Recorder:
    calls: int = 0

    def bump(self) -> None:
        self.calls += 1


def constant_policy(value: float):
    def policy(state: object) -> Schedule:
        return schedule_with(value)

    return policy


def echo_policy(state: object) -> Schedule:
    return schedule_with(float(state))


def npv_evaluator(recorder: Recorder, npv_of):
    def evaluator(schedule: Schedule) -> Evaluation:
        recorder.bump()
        return npv_of(schedule)

    return evaluator


def test_a_stationary_policy_converges_on_the_first_comparison() -> None:
    recorder = Recorder()

    def npv_of(schedule: Schedule) -> Evaluation:
        return Evaluation(npv=100.0, state=10.0)

    result = resolve(
        policy=constant_policy(10.0),
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=10.0,
        iteration_cap=DEFAULT_BUDGETS.fixed_point_iteration_cap,
    )
    assert result.converged is True
    assert result.self_consistent is True
    assert result.iterations == 1
    assert recorder.calls == 1


def test_convergence_is_decided_by_the_hash_not_by_the_iteration_count() -> None:
    recorder = Recorder()
    seen: list[str] = []

    def npv_of(schedule: Schedule) -> Evaluation:
        seen.append(hash_schedule(schedule))
        return Evaluation(npv=1.0, state=7.0)

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=7.0,
        iteration_cap=DEFAULT_BUDGETS.fixed_point_iteration_cap,
    )
    assert result.converged is True
    assert result.schedule_hash == hash_schedule(schedule_with(7.0))
    assert seen == [result.schedule_hash]


def test_a_walk_that_settles_converges_when_the_hash_repeats() -> None:
    recorder = Recorder()
    route = {5.0: 6.0, 6.0: 7.0, 7.0: 7.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=current, state=route[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=5.0,
        iteration_cap=DEFAULT_BUDGETS.fixed_point_iteration_cap,
    )
    assert result.converged is True
    assert result.schedule_hash == hash_schedule(schedule_with(7.0))
    assert result.iterations == 3
    assert result.hashes() == (
        hash_schedule(schedule_with(5.0)),
        hash_schedule(schedule_with(6.0)),
        hash_schedule(schedule_with(7.0)),
    )


def test_an_oscillating_input_does_not_loop_forever() -> None:
    recorder = Recorder()
    flip = {1.0: 2.0, 2.0: 1.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=current, state=flip[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=6,
    )
    assert result.converged is False
    assert result.iterations == 6
    assert len(result.visited) == 6


def test_hitting_the_cap_reports_not_converged() -> None:
    recorder = Recorder()
    step = {float(k): float(k + 1) for k in range(100)}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=current, state=step[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=0.0,
        iteration_cap=4,
    )
    assert result.converged is False
    assert result.iterations == 4


def test_at_the_cap_the_best_by_npv_is_reevaluated_once_more() -> None:
    recorder = Recorder()
    flip = {1.0: 2.0, 2.0: 1.0}
    npv = {1.0: 10.0, 2.0: 50.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=npv[current], state=flip[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=4,
    )
    assert result.converged is False
    assert result.schedule_hash == hash_schedule(schedule_with(2.0))
    assert recorder.calls == 5


def test_the_reported_npv_comes_from_the_final_reevaluation() -> None:
    recorder = Recorder()
    flip = {1.0: 2.0, 2.0: 1.0}
    drift = {"first": True}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        if current == 2.0 and not drift["first"]:
            return Evaluation(npv=7.0, state=flip[current])
        if current == 2.0:
            drift["first"] = False
            return Evaluation(npv=50.0, state=flip[current])
        return Evaluation(npv=10.0, state=flip[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=4,
    )
    assert result.npv == 7.0
    assert result.best_visited().npv == 50.0


def test_a_reevaluated_candidate_that_reproduces_itself_is_self_consistent() -> None:
    recorder = Recorder()
    calls: dict[float, int] = {}
    npv = {1.0: 1.0, 2.0: 99.0, 3.0: 2.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        calls[current] = calls.get(current, 0) + 1
        if current == 2.0 and calls[current] == 1:
            return Evaluation(npv=npv[current], state=3.0)
        if current == 2.0:
            return Evaluation(npv=npv[current], state=2.0)
        return Evaluation(npv=npv[current], state=current + 1.0)

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=3,
    )
    assert result.converged is False
    assert result.schedule_hash == hash_schedule(schedule_with(2.0))
    assert result.self_consistent is True


def test_a_candidate_whose_response_points_elsewhere_is_flagged() -> None:
    recorder = Recorder()
    route = {1.0: 2.0, 2.0: 3.0, 3.0: 4.0}
    npv = {1.0: 1.0, 2.0: 99.0, 3.0: 2.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=npv[current], state=route[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=3,
    )
    assert result.converged is False
    assert result.schedule_hash == hash_schedule(schedule_with(2.0))
    assert result.self_consistent is False


def test_an_oscillating_candidate_is_not_self_consistent() -> None:
    recorder = Recorder()
    flip = {1.0: 2.0, 2.0: 1.0}
    npv = {1.0: 10.0, 2.0: 50.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=npv[current], state=flip[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=4,
    )
    assert result.self_consistent is False


def test_the_result_is_deterministic_across_repeated_runs() -> None:
    flip = {1.0: 2.0, 2.0: 1.0}
    npv = {1.0: 10.0, 2.0: 50.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=npv[current], state=flip[current])

    outcomes = [
        resolve(
            policy=echo_policy,
            evaluator=npv_evaluator(Recorder(), npv_of),
            initial_state=1.0,
            iteration_cap=5,
        )
        for _ in range(3)
    ]
    assert {o.schedule_hash for o in outcomes} == {outcomes[0].schedule_hash}
    assert {o.npv for o in outcomes} == {outcomes[0].npv}
    assert {o.converged for o in outcomes} == {False}
    assert {o.hashes() for o in outcomes} == {outcomes[0].hashes()}


def test_the_evaluator_is_an_argument_not_a_builtin_stub() -> None:
    calls: list[str] = []

    def first(schedule: Schedule) -> Evaluation:
        calls.append("first")
        return Evaluation(npv=1.0, state=3.0)

    def second(schedule: Schedule) -> Evaluation:
        calls.append("second")
        return Evaluation(npv=2.0, state=3.0)

    resolve(
        policy=echo_policy,
        evaluator=first,
        initial_state=3.0,
        iteration_cap=3,
    )
    resolve(
        policy=echo_policy,
        evaluator=second,
        initial_state=3.0,
        iteration_cap=3,
    )
    assert calls == ["first", "second"]


def test_the_iteration_cap_comes_from_the_config_budget() -> None:
    assert DEFAULT_BUDGETS.fixed_point_iteration_cap > 0
    recorder = Recorder()
    step = {float(k): float(k + 1) for k in range(100)}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=current, state=step[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=0.0,
        iteration_cap=DEFAULT_BUDGETS.fixed_point_iteration_cap,
    )
    assert result.iterations == DEFAULT_BUDGETS.fixed_point_iteration_cap


def test_a_non_positive_cap_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve(
            policy=echo_policy,
            evaluator=lambda schedule: Evaluation(npv=0.0, state=1.0),
            initial_state=1.0,
            iteration_cap=0,
        )


def test_a_converged_result_cannot_claim_to_be_inconsistent() -> None:
    visited = (
        Visited(
            iteration=0,
            schedule=schedule_with(1.0),
            schedule_hash=hash_schedule(schedule_with(1.0)),
            npv=1.0,
        ),
    )
    with pytest.raises(ValueError):
        FixedPointResult(
            schedule=schedule_with(1.0),
            schedule_hash=hash_schedule(schedule_with(1.0)),
            npv=1.0,
            converged=True,
            self_consistent=False,
            iterations=1,
            visited=visited,
        )


def test_a_result_without_visited_schedules_is_rejected() -> None:
    with pytest.raises(ValueError):
        FixedPointResult(
            schedule=schedule_with(1.0),
            schedule_hash=hash_schedule(schedule_with(1.0)),
            npv=1.0,
            converged=False,
            self_consistent=False,
            iterations=0,
            visited=(),
        )


def test_the_best_visited_breaks_ties_by_the_earliest_iteration() -> None:
    recorder = Recorder()
    flip = {1.0: 2.0, 2.0: 1.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=42.0, state=flip[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=4,
    )
    assert result.best_visited().iteration == 0
    assert result.schedule_hash == hash_schedule(schedule_with(1.0))


def test_every_visited_schedule_is_recorded_with_its_hash() -> None:
    recorder = Recorder()
    route = {1.0: 2.0, 2.0: 3.0, 3.0: 4.0, 4.0: 5.0}

    def npv_of(schedule: Schedule) -> Evaluation:
        current = schedule.control_events[0].value
        return Evaluation(npv=current, state=route[current])

    result = resolve(
        policy=echo_policy,
        evaluator=npv_evaluator(recorder, npv_of),
        initial_state=1.0,
        iteration_cap=4,
    )
    assert len(result.visited) == 4
    for entry in result.visited:
        assert entry.schedule_hash == hash_schedule(entry.schedule)
    assert len(set(result.hashes())) == 4
