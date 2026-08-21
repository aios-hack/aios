from __future__ import annotations

from dataclasses import replace

import pytest

from aios_backend.core.contracts import EventKind, Rule

from aios_backend.domain.policy import (
    RuleContext,
    RuleFlags,
    WellMemory,
    apply_rule,
    default_theta,
    make_theta,
)
from aios_backend.domain.policy.rules import r6
from aios_backend.domain.policy.tests.conftest import influence_of, injector, memory_of, producer, state_of

CANDIDATE = "43"
NEARLY_DEAD_WATERCUT = 0.985
STILL_GOOD_WATERCUT = 0.40


def context_with(
    context: RuleContext, sensitivity: float, memory=None
) -> RuleContext:
    influence = influence_of(
        producers=("42",),
        injectors=("101", CANDIDATE),
        matrix=((0.5, sensitivity),),
    )
    return replace(
        context,
        influence=influence,
        memory=memory if memory is not None else memory_of(),
    )


def wells(watercut: float):
    return (
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.5, setpoint=50.0),
        producer(
            CANDIDATE, liquid_rate_m3_per_day=60.0, watercut=watercut, setpoint=60.0
        ),
        injector("101", injection_rate_m3_per_day=80.0),
    )


def outcome_of(context: RuleContext, watercut: float, sensitivity: float, theta=None):
    return r6.apply(
        state_of(*wells(watercut)),
        context_with(context, sensitivity),
        theta if theta is not None else default_theta(),
    )


def test_rule_states_its_criterion_in_field_language() -> None:
    assert r6.ADMISSION_CRITERION.endswith(".")
    assert len(r6.ADMISSION_CRITERION.split()) <= 20


def test_r6_spends_one_theta() -> None:
    assert r6.THETA_NAMES == ("r6_payback_years",)


def test_a_watered_out_well_over_a_strong_neighbour_is_converted(
    context: RuleContext,
) -> None:
    outcome = outcome_of(context, NEARLY_DEAD_WATERCUT, sensitivity=2.0)
    assert [d.kind for d in outcome.decisions] == [EventKind.CONVERT_INJ]
    assert [e.decision for e in outcome.trace] == ["CONVERT_INJ"]


def test_a_still_producing_well_is_kept_as_a_producer(
    context: RuleContext,
) -> None:
    outcome = outcome_of(context, STILL_GOOD_WATERCUT, sensitivity=0.05)
    assert outcome.decisions == ()
    assert [e.decision for e in outcome.trace] == ["HOLD_AS_PRODUCER"]


def test_the_conversion_costs_exactly_the_base_price_with_no_pump_on_top(
    context: RuleContext,
) -> None:
    entry = outcome_of(context, NEARLY_DEAD_WATERCUT, sensitivity=2.0).trace[0]
    assert entry.inputs["conversion_base_cost_rub"] == (
        context.normatives.conversion_base_cost_rub
    )
    assert "esp" not in " ".join(entry.inputs).lower()


def test_the_trace_compares_both_roles_in_money(context: RuleContext) -> None:
    entry = outcome_of(context, NEARLY_DEAD_WATERCUT, sensitivity=2.0).trace[0]
    assert "annual_margin_as_producer_rub" in entry.inputs
    assert "annual_value_as_injector_rub" in entry.inputs
    assert entry.inputs["annual_delta_rub"] == pytest.approx(
        entry.inputs["annual_value_as_injector_rub"]
        - entry.inputs["annual_margin_as_producer_rub"]
    )
    assert entry.inputs["payback_years"] > 0.0


def test_a_shorter_payback_horizon_converts_less_readily(
    context: RuleContext,
) -> None:
    patient = make_theta({"r6_payback_years": 15.0})
    impatient = make_theta({"r6_payback_years": 1.0})
    lenient = outcome_of(context, NEARLY_DEAD_WATERCUT, 0.02, theta=patient)
    strict = outcome_of(context, NEARLY_DEAD_WATERCUT, 0.02, theta=impatient)
    assert lenient.decisions != ()
    assert strict.decisions == ()


def test_an_already_converted_well_is_not_converted_twice(
    context: RuleContext,
) -> None:
    memory = memory_of(**{CANDIDATE: WellMemory(converted_to_injection=True)})
    outcome = r6.apply(
        state_of(*wells(NEARLY_DEAD_WATERCUT)),
        context_with(context, 2.0, memory),
        default_theta(),
    )
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_conversion_needs_the_measured_influence_matrix(
    context: RuleContext,
) -> None:
    with pytest.raises(ValueError, match="измеренную λ"):
        r6.apply(state_of(*wells(NEARLY_DEAD_WATERCUT)), context, default_theta())


def test_a_negative_delta_never_pays_back() -> None:
    assert r6.payback_years(5_000_000.0, -1.0) == float("inf")
    assert r6.payback_years(5_000_000.0, 0.0) == float("inf")
    assert r6.payback_years(5_000_000.0, 1_000_000.0) == pytest.approx(5.0)


def test_disabled_r6_makes_no_decisions_and_no_records(
    context: RuleContext,
) -> None:
    off = apply_rule(
        Rule.R6,
        state_of(*wells(NEARLY_DEAD_WATERCUT)),
        context_with(context, 2.0),
        default_theta(),
        RuleFlags().with_disabled(Rule.R6),
    )
    assert off.decisions == ()
    assert off.trace == ()


def test_producer_outside_lambda_follows_the_deck_conversion(
    context: RuleContext,
) -> None:
    """Скважина вне окна λ переводится на том шаге, где её переводит дек.

    Прежний `continue` был замкнутым кругом: чтобы правило разрешило перевести
    скважину в нагнетательные, она должна была уже быть нагнетательной в
    измеренной λ. Скважина, которую дек переводит после окна замера, в окне
    добывала и в матрицу попасть не могла — восемь таких скважин базового
    дека мы не переводили вовсе, и это 395 м³/сут недокачки на прогоне G7.
    """

    influence = influence_of(
        producers=("42",), injectors=("101",), matrix=((0.6,),)
    )
    ctx = replace(
        context,
        influence=influence,
        baseline_conversion_step={"77": 4},
    )
    state = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        producer("77", liquid_rate_m3_per_day=12.0, watercut=NEARLY_DEAD_WATERCUT),
        injector("101", injection_rate_m3_per_day=100.0),
    )
    state = replace(state, control_step=4)
    outcome = apply_rule(Rule.R6, state, ctx, default_theta(), RuleFlags())
    converted = [
        event for event in outcome.decisions if event.kind is EventKind.CONVERT_INJ
    ]
    assert [event.well for event in converted] == ["77"]
    entry = next(item for item in outcome.trace if item.well == "77")
    assert entry.decision == "FOLLOW_BASELINE_CONVERSION"
    assert entry.inputs["baseline_conversion_step"] == pytest.approx(4.0)


def test_producer_outside_lambda_waits_for_the_deck_step(
    context: RuleContext,
) -> None:
    """Раньше дека не переводим: шаг перевода — тоже данные дека, не наш выбор."""

    influence = influence_of(
        producers=("42",), injectors=("101",), matrix=((0.6,),)
    )
    ctx = replace(
        context, influence=influence, baseline_conversion_step={"77": 40}
    )
    state = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        producer("77", liquid_rate_m3_per_day=12.0, watercut=NEARLY_DEAD_WATERCUT),
        injector("101", injection_rate_m3_per_day=100.0),
    )
    state = replace(state, control_step=39)
    outcome = apply_rule(Rule.R6, state, ctx, default_theta(), RuleFlags())
    assert not [
        event for event in outcome.decisions if event.well == "77"
    ]


def test_producer_outside_lambda_and_outside_the_deck_is_left_alone(
    context: RuleContext,
) -> None:
    """Дек её не переводит — и мы не переводим: судить по-прежнему не на чем."""

    influence = influence_of(
        producers=("42",), injectors=("101",), matrix=((0.6,),)
    )
    ctx = replace(context, influence=influence)
    state = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        producer("77", liquid_rate_m3_per_day=12.0, watercut=NEARLY_DEAD_WATERCUT),
        injector("101", injection_rate_m3_per_day=100.0),
    )
    state = replace(state, control_step=100)
    outcome = apply_rule(Rule.R6, state, ctx, default_theta(), RuleFlags())
    assert not [event for event in outcome.decisions if event.well == "77"]
