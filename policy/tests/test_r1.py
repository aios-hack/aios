from __future__ import annotations

from dataclasses import replace

import pytest

from contracts import EventKind, NormativeSet, Rule

from policy import RuleContext, RuleFlags, apply_rule, default_theta
from policy.rules import r1
from policy.tests.conftest import (
    OIL_DENSITY_T_PER_M3,
    influence_of,
    injector,
    producer,
    state_of,
)


def two_producer_context(context: RuleContext, budget: float = 400.0) -> RuleContext:
    influence = influence_of(
        producers=("42", "43"),
        injectors=("101", "102"),
        matrix=((0.6, 0.0), (0.0, 0.6)),
    )
    return replace(
        context, influence=influence, injection_budget_m3_per_day=budget
    )


WASHED_OUT_WATERCUT = 0.9995


def two_producer_state():
    return state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        producer("43", liquid_rate_m3_per_day=40.0, watercut=WASHED_OUT_WATERCUT),
        injector("101", injection_rate_m3_per_day=200.0),
        injector("102", injection_rate_m3_per_day=200.0),
    )


def test_r1_has_one_theta_parameter() -> None:
    assert r1.THETA_NAMES == ("r1_lag_months",)


def test_marginal_value_dimension_is_rub_per_m3_of_injection(
    context: RuleContext, normatives: NormativeSet
) -> None:
    ctx = two_producer_context(context)
    state = two_producer_state()
    value, inputs = r1.marginal_value_rub_per_m3(state, ctx, "101")
    expected_gross = 0.6 * (1.0 - 0.50) * OIL_DENSITY_T_PER_M3 * 8360.0
    assert inputs["gross_value_rub_per_m3"] == pytest.approx(expected_gross)
    assert value == pytest.approx(
        expected_gross - normatives.opex_injection_rub_per_m3
    )


def test_watercut_enters_as_separate_factor(context: RuleContext) -> None:
    ctx = two_producer_context(context)
    clean = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.0),
        producer("43", liquid_rate_m3_per_day=40.0, watercut=0.98),
        injector("101", injection_rate_m3_per_day=200.0),
        injector("102", injection_rate_m3_per_day=200.0),
    )
    half = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.5),
        producer("43", liquid_rate_m3_per_day=40.0, watercut=0.98),
        injector("101", injection_rate_m3_per_day=200.0),
        injector("102", injection_rate_m3_per_day=200.0),
    )
    gross_clean = r1.marginal_value_rub_per_m3(clean, ctx, "101")[1][
        "gross_value_rub_per_m3"
    ]
    gross_half = r1.marginal_value_rub_per_m3(half, ctx, "101")[1][
        "gross_value_rub_per_m3"
    ]
    assert gross_half == pytest.approx(gross_clean * 0.5)


def test_water_goes_to_the_clean_side(context: RuleContext) -> None:
    ctx = two_producer_context(context, budget=400.0)
    outcome = apply_rule(Rule.R1, two_producer_state(), ctx, default_theta(), RuleFlags())
    targets = {event.well: event.value for event in outcome.decisions}
    assert targets["101"] == pytest.approx(400.0)
    assert targets["102"] == pytest.approx(0.0)


def test_budget_is_not_exceeded(context: RuleContext) -> None:
    influence = influence_of(
        producers=("42", "43"),
        injectors=("101", "102"),
        matrix=((0.6, 0.2), (0.1, 0.5)),
    )
    ctx = replace(context, influence=influence, injection_budget_m3_per_day=350.0)
    outcome = apply_rule(Rule.R1, two_producer_state(), ctx, default_theta(), RuleFlags())
    assert sum(event.value for event in outcome.decisions) == pytest.approx(350.0)


def test_washed_out_zone_gets_nothing(context: RuleContext) -> None:
    influence = influence_of(
        producers=("43",), injectors=("102",), matrix=((0.6,),)
    )
    ctx = replace(context, influence=influence, injection_budget_m3_per_day=300.0)
    state = state_of(
        producer("43", liquid_rate_m3_per_day=40.0, watercut=0.999),
        injector("102", injection_rate_m3_per_day=200.0),
    )
    outcome = apply_rule(Rule.R1, state, ctx, default_theta(), RuleFlags())
    assert [event.value for event in outcome.decisions] == [0.0]
    assert outcome.trace[0].inputs["marginal_value_rub_per_m3"] < 0.0


def test_trace_carries_decision_numbers(context: RuleContext) -> None:
    ctx = two_producer_context(context)
    outcome = apply_rule(Rule.R1, two_producer_state(), ctx, default_theta(), RuleFlags())
    entry = next(e for e in outcome.trace if e.well == "101")
    assert entry.rule is Rule.R1
    assert entry.decision == "SET_RATE"
    for key in (
        "marginal_value_rub_per_m3",
        "opex_injection_rub_per_m3",
        "injection_budget_m3_per_day",
        "share_of_budget",
        "target_rate_m3_per_day",
        "theta_r1_lag_months",
        "lambda_lag_months",
    ):
        assert key in entry.inputs


def test_decisions_are_set_rate(context: RuleContext) -> None:
    ctx = two_producer_context(context)
    outcome = apply_rule(Rule.R1, two_producer_state(), ctx, default_theta(), RuleFlags())
    assert {event.kind for event in outcome.decisions} == {EventKind.SET_RATE}


def test_missing_lambda_raises_not_returns_zero(context: RuleContext) -> None:
    ctx = replace(context, injection_budget_m3_per_day=300.0)
    with pytest.raises(ValueError):
        apply_rule(Rule.R1, two_producer_state(), ctx, default_theta(), RuleFlags())


def test_missing_budget_raises(context: RuleContext) -> None:
    influence = influence_of(
        producers=("42",), injectors=("101",), matrix=((0.6,),)
    )
    ctx = replace(context, influence=influence)
    with pytest.raises(ValueError):
        apply_rule(Rule.R1, two_producer_state(), ctx, default_theta(), RuleFlags())


def test_injector_outside_lambda_holds_its_baseline_rate(
    context: RuleContext, normatives: NormativeSet
) -> None:
    """Нагнетательная вне окна замера держит базовую уставку, а не ноль.

    Кампания Плакетта—Бермана покрыла 22 нагнетательных из 41, а невошедшие
    несут 46% закачки месторождения. Пока R1 их не адресовал, плотный слой
    оставлял их на нуле, и отсутствие замера превращалось в решение
    заглушить: на прогоне G7 это 662 м³/сут из 835 всей недокачки. Ценность
    их закачки по-прежнему не считается — она неизвестна, а не равна нулю, —
    поэтому в дележе бюджета они не участвуют.
    """

    ctx = replace(
        two_producer_context(context),
        baseline_injection_m3_per_day={"103": 70.0},
    )
    state = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        producer("43", liquid_rate_m3_per_day=40.0, watercut=WASHED_OUT_WATERCUT),
        injector("101", injection_rate_m3_per_day=200.0),
        injector("102", injection_rate_m3_per_day=200.0),
        injector("103", injection_rate_m3_per_day=70.0),
    )
    outcome = apply_rule(Rule.R1, state, ctx, default_theta(), RuleFlags())
    by_well = {event.well: event for event in outcome.decisions}

    assert by_well["103"].kind is EventKind.SET_RATE
    assert by_well["103"].value == pytest.approx(70.0)

    entry = next(item for item in outcome.trace if item.well == "103")
    assert entry.decision == "HOLD_BASELINE_OUTSIDE_LAMBDA"
    assert entry.inputs["outside_lambda_window"] == 1.0

    # Фонд воды у месторождения один: удержанный базовый уровень вычитается
    # из бюджета, а не прибавляется сверх него. Иначе сумма выходит за лимит
    # участка и агент участка срезает множителем всех, включая измеренных.
    measured = sum(by_well[well].value or 0.0 for well in ("101", "102"))
    budget = ctx.injection_budget_m3_per_day
    assert measured == pytest.approx(budget - 70.0)
    assert measured + (by_well["103"].value or 0.0) == pytest.approx(budget)


def test_injector_outside_lambda_without_baseline_is_shut_explicitly(
    context: RuleContext,
) -> None:
    """Без базовой уставки скважина получает явный ноль, а не молчание.

    Разница существенна: молчание правила плотный слой трактует сам, и
    поведение зависит от того, что осталось в состоянии. Явный ноль — это
    решение, и оно видно в трассе.
    """

    ctx = two_producer_context(context)
    state = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        producer("43", liquid_rate_m3_per_day=40.0, watercut=WASHED_OUT_WATERCUT),
        injector("101", injection_rate_m3_per_day=200.0),
        injector("102", injection_rate_m3_per_day=200.0),
        injector("103", injection_rate_m3_per_day=70.0),
    )
    outcome = apply_rule(Rule.R1, state, ctx, default_theta(), RuleFlags())
    by_well = {event.well: event for event in outcome.decisions}
    assert by_well["103"].value == pytest.approx(0.0)


def test_budget_fills_wells_by_value_up_to_their_capacity(
    context: RuleContext,
) -> None:
    """Вода идёт по убыванию ценности до потолка, остаток — следующей.

    Пропорциональный дележ давал скважине воду по величине предельной
    ценности, то есть по рублям на кубометр, а не по ёмкости. Скважина, чья
    приёмистость 30 м³/сут, получала сотни, срез потолком дальше по тракту
    эту воду никому не отдавал, и бюджет расходовался частично: на прогоне
    G7 восемнадцать измеренных скважин из двадцати двух стояли на потолке все
    224 шага при 683 м³/сут неиспользованной ёмкости у остальных.
    """

    influence = influence_of(
        producers=("42",),
        injectors=("101", "102", "103"),
        # 101 ценнее 102, 102 ценнее 103
        matrix=((0.9, 0.6, 0.3),),
    )
    ctx = replace(
        context,
        influence=influence,
        injection_budget_m3_per_day=300.0,
        injection_cap_m3_per_day={"101": 100.0, "102": 150.0, "103": 500.0},
    )
    state = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        injector("101", injection_rate_m3_per_day=10.0),
        injector("102", injection_rate_m3_per_day=10.0),
        injector("103", injection_rate_m3_per_day=10.0),
    )
    outcome = apply_rule(Rule.R1, state, ctx, default_theta(), RuleFlags())
    targets = {event.well: event.value for event in outcome.decisions}

    assert targets["101"] == pytest.approx(100.0)  # упёрлась в свой потолок
    assert targets["102"] == pytest.approx(150.0)  # тоже, остаток пошёл дальше
    assert targets["103"] == pytest.approx(50.0)   # добирает то, что осталось
    assert sum(targets.values()) == pytest.approx(300.0)


def test_capacity_shortfall_leaves_budget_unspent_and_says_so(
    context: RuleContext,
) -> None:
    """Если ёмкости меньше бюджета, лишнее остаётся неразданным и видно в трассе.

    Правило не имеет права придумывать скважине приёмистость сверх её
    исторической: непринятая вода — это факт про фонд, а не про бюджет.
    """

    influence = influence_of(
        producers=("42",), injectors=("101", "102"), matrix=((0.9, 0.6),)
    )
    ctx = replace(
        context,
        influence=influence,
        injection_budget_m3_per_day=1000.0,
        injection_cap_m3_per_day={"101": 100.0, "102": 150.0},
    )
    state = state_of(
        producer("42", liquid_rate_m3_per_day=40.0, watercut=0.50),
        injector("101", injection_rate_m3_per_day=10.0),
        injector("102", injection_rate_m3_per_day=10.0),
    )
    outcome = apply_rule(Rule.R1, state, ctx, default_theta(), RuleFlags())
    targets = {event.well: event.value for event in outcome.decisions}
    assert sum(targets.values()) == pytest.approx(250.0)
    entry = next(item for item in outcome.trace if item.well == "101")
    assert entry.inputs["budget_unallocated_m3_per_day"] == pytest.approx(750.0)


def test_unprofitable_injector_gets_nothing_even_with_capacity(
    context: RuleContext,
) -> None:
    """Отрицательная предельная ценность не спасается свободной ёмкостью."""

    ctx = replace(
        two_producer_context(context, budget=400.0),
        injection_cap_m3_per_day={"101": 1000.0, "102": 1000.0},
    )
    outcome = apply_rule(
        Rule.R1, two_producer_state(), ctx, default_theta(), RuleFlags()
    )
    targets = {event.well: event.value for event in outcome.decisions}
    assert targets["102"] == pytest.approx(0.0)
    assert targets["101"] == pytest.approx(400.0)
