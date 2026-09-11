from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core.contracts import Constraints, EventKind, Rule

from backend.contexts.policy.domain.flags import (
    DEFAULT_FEATURE_FLAGS,
    WATERCUT_CAP_FEATURE,
    RuleFlags,
)
from backend.contexts.policy.domain.levels import (
    PRODUCTION_FLOOR_MET,
    PRODUCTION_FLOOR_NOT_SET,
    PRODUCTION_FLOOR_UNREACHABLE,
    GroupLimit,
    binding_watercut_limit,
    check_production_floor,
    decide_group,
    watercut_cap_shutins,
)
from backend.contexts.policy.domain.rules import apply_rule
from backend.contexts.policy.domain.rules.r1 import held_target
from backend.contexts.policy.domain.rules.r5 import corridor_bounds
from backend.contexts.policy.domain.state import RuleContext
from backend.contexts.policy.domain.theta import default_theta, make_theta
from backend.domain.policy.tests.conftest import (
    OIL_DENSITY_T_PER_M3,
    groups_of,
    influence_of,
    injector,
    producer,
    state_of,
)


def _lambda_of_one() -> object:
    return influence_of(
        producers=("42",),
        injectors=("101",),
        matrix=((3.0,),),
    )


def _r1_context(context: RuleContext, **overrides: object) -> RuleContext:
    base = replace(
        context,
        influence=_lambda_of_one(),
        injection_budget_m3_per_day=1000.0,
    )
    return replace(base, **overrides)


def test_setpoint_outside_lambda_is_capped_by_injectivity(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.5),
        injector("101", injection_rate_m3_per_day=100.0),
        injector("202", injection_rate_m3_per_day=400.0),
    )
    scoped = _r1_context(
        context,
        baseline_injection_m3_per_day={"202": 400.0},
        injection_cap_m3_per_day={"202": 250.0},
    )
    outcome = apply_rule(Rule.R1, state, scoped, default_theta(), RuleFlags())
    held = [e for e in outcome.decisions if e.well == "202"]
    assert len(held) == 1
    assert held[0].value == 250.0

    entry = next(e for e in outcome.trace if e.well == "202")
    assert entry.decision == "HOLD_BASELINE_CAPPED_OUTSIDE_LAMBDA"
    assert entry.inputs["baseline_rate_m3_per_day"] == 400.0
    assert entry.inputs["injection_cap_m3_per_day"] == 250.0
    assert entry.inputs["capped_by_injectivity"] == 1.0


def test_setpoint_outside_lambda_is_untouched_without_a_cap(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.5),
        injector("101", injection_rate_m3_per_day=100.0),
        injector("202", injection_rate_m3_per_day=400.0),
    )
    scoped = _r1_context(
        context, baseline_injection_m3_per_day={"202": 400.0}
    )
    outcome = apply_rule(Rule.R1, state, scoped, default_theta(), RuleFlags())
    held = next(e for e in outcome.decisions if e.well == "202")
    assert held.value == 400.0
    entry = next(e for e in outcome.trace if e.well == "202")
    assert entry.decision == "HOLD_BASELINE_OUTSIDE_LAMBDA"
    assert entry.inputs["capped_by_injectivity"] == 0.0


def test_capped_hold_frees_budget_for_measured_wells(
    context: RuleContext,
) -> None:
    state = state_of(
        producer("42", liquid_rate_m3_per_day=50.0, watercut=0.5),
        injector("101", injection_rate_m3_per_day=100.0),
        injector("202", injection_rate_m3_per_day=400.0),
    )
    scoped = _r1_context(
        context,
        baseline_injection_m3_per_day={"202": 400.0},
        injection_cap_m3_per_day={"202": 250.0},
    )
    outcome = apply_rule(Rule.R1, state, scoped, default_theta(), RuleFlags())
    entry = next(e for e in outcome.trace if e.well == "101")
    assert entry.inputs["budget_held_outside_lambda_m3_per_day"] == 250.0
    assert entry.inputs["budget_for_measured_m3_per_day"] == 750.0


def test_held_target_rejects_a_negative_cap() -> None:
    with pytest.raises(ValueError):
        held_target({"202": 400.0}, {"202": -1.0}, "202")


def _corridor(minimum: float, maximum: float, enforcement: str) -> Constraints:
    return Constraints(
        infrastructure={
            "compensation_min": minimum,
            "compensation_max": maximum,
            "compensation_enforcement": enforcement,
        }
    )


def test_hard_corridor_clamps_theta(context: RuleContext) -> None:
    scoped = replace(context, constraints=_corridor(0.95, 1.05, "hard"))
    low, high, enforced = corridor_bounds(scoped, 0.5, 1.6)
    assert (low, high) == (0.95, 1.05)
    assert enforced is True


def test_diagnostic_corridor_leaves_theta_untouched(
    context: RuleContext,
) -> None:
    scoped = replace(context, constraints=_corridor(0.95, 1.05, "diagnostic"))
    low, high, enforced = corridor_bounds(scoped, 0.5, 1.6)
    assert (low, high) == (0.5, 1.6)
    assert enforced is False


def test_absent_corridor_leaves_theta_untouched(context: RuleContext) -> None:
    low, high, enforced = corridor_bounds(context, 0.5, 1.6)
    assert (low, high) == (0.5, 1.6)
    assert enforced is False


def _compensation_state() -> object:
    return state_of(
        producer("42", liquid_rate_m3_per_day=100.0, watercut=0.5),
        injector("101", injection_rate_m3_per_day=200.0),
    )


def _compensation_context(context: RuleContext, constraints: Constraints):
    return replace(
        context,
        constraints=constraints,
        groups=groups_of({"G1": ("42", "101")}),
        group_injection_m3_per_day={"G1": 200.0},
        group_offtake_m3_per_day={"G1": 100.0},
    )


def test_hard_corridor_keeps_r5_inside_the_case_window(
    context: RuleContext,
) -> None:
    state = _compensation_state()
    scoped = _compensation_context(context, _corridor(0.95, 1.05, "hard"))
    theta = make_theta(
        {"r5_compensation_low": 0.5, "r5_compensation_high": 1.6}
    )
    outcome = apply_rule(Rule.R5, state, scoped, theta, RuleFlags())
    entry = next(e for e in outcome.trace if e.well == "101")
    assert entry.inputs["corridor_enforced"] == 1.0
    assert entry.inputs["target_compensation"] <= 1.05 + 1e-9
    assert entry.inputs["theta_r5_compensation_high"] == 1.6


def test_diagnostic_corridor_reproduces_the_previous_decision(
    context: RuleContext,
) -> None:
    state = _compensation_state()
    theta = make_theta(
        {"r5_compensation_low": 0.5, "r5_compensation_high": 1.6}
    )
    without = apply_rule(
        Rule.R5, state, _compensation_context(context, Constraints()), theta, RuleFlags()
    )
    diagnostic = apply_rule(
        Rule.R5,
        state,
        _compensation_context(context, _corridor(0.95, 1.05, "diagnostic")),
        theta,
        RuleFlags(),
    )
    assert without.decisions == diagnostic.decisions
    for left, right in zip(without.trace, diagnostic.trace):
        assert left.decision == right.decision
        assert left.inputs == right.inputs


def test_empty_intersection_with_the_case_corridor_is_reported(
    context: RuleContext,
) -> None:
    scoped = replace(context, constraints=_corridor(0.95, 1.05, "hard"))
    bounded = corridor_bounds(scoped, 0.5, 1.6)
    assert bounded[0] == 0.95 and bounded[1] == 1.05
    pinned = corridor_bounds(scoped, 1.2, 1.6)
    assert pinned[0] == pinned[1] == 1.05


WATERCUT_WELLS = (
    producer("41", liquid_rate_m3_per_day=200.0, watercut=0.99),
    producer("42", liquid_rate_m3_per_day=150.0, watercut=0.96),
    producer("43", liquid_rate_m3_per_day=50.0, watercut=0.80),
)


def _watercut_context(context: RuleContext, limit: float | None) -> RuleContext:
    constraints = (
        Constraints() if limit is None else Constraints(watercut_limits={2010: limit})
    )
    return replace(
        context,
        constraints=constraints,
        groups=groups_of({"G1": ("41", "42", "43")}),
    )


def test_binding_watercut_limit_takes_the_tightest_year(
    context: RuleContext,
) -> None:
    scoped = replace(
        context, constraints=Constraints(watercut_limits={2010: 0.95, 2011: 0.9})
    )
    assert binding_watercut_limit(scoped) == 0.9
    assert binding_watercut_limit(context) is None


def test_wateriest_wells_are_shut_first_until_the_limit_holds(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _watercut_context(context, 0.9)
    shut, before, after = watercut_cap_shutins(
        state, scoped, (), ("41", "42", "43"), 0.9
    )
    assert shut == ("41", "42")
    assert before > 0.9
    assert after <= 0.9

    partial = state_of(*WATERCUT_WELLS[1:])
    fewer, _before, after_partial = watercut_cap_shutins(
        partial, scoped, (), ("42", "43"), 0.9
    )
    assert fewer == ("42",)
    assert after_partial <= 0.9


def test_watercut_shutins_stop_as_soon_as_the_limit_holds(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _watercut_context(context, 0.99)
    shut, _before, after = watercut_cap_shutins(
        state, scoped, (), ("41", "42", "43"), 0.99
    )
    assert shut == ()
    assert after <= 0.99


def test_shutting_every_producer_still_meets_the_limit(
    context: RuleContext,
) -> None:
    state = state_of(producer("41", liquid_rate_m3_per_day=100.0, watercut=0.98))
    scoped = _watercut_context(context, 0.5)
    shut, before, after = watercut_cap_shutins(state, scoped, (), ("41",), 0.5)
    assert shut == ("41",)
    assert before > 0.5
    assert after <= 0.5


def _limit_of(group_id: str = "G1") -> GroupLimit:
    return GroupLimit(
        group_id=group_id,
        injection_m3_per_day=0.0,
        share_of_field=1.0,
        demand_rub_per_m3=0.0,
    )


def _r0_only() -> RuleFlags:
    return RuleFlags(enabled={rule: rule is Rule.R0 for rule in Rule})


def test_watercut_cap_feature_is_off_by_default() -> None:
    assert DEFAULT_FEATURE_FLAGS[WATERCUT_CAP_FEATURE] is False
    assert RuleFlags().feature_on(WATERCUT_CAP_FEATURE) is False


def test_case_with_a_watercut_ceiling_of_zero_nine_yields_a_clean_candidate(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _watercut_context(context, 0.9)
    flags = _r0_only().with_feature(WATERCUT_CAP_FEATURE, True)
    decision = decide_group(state, scoped, default_theta(), flags, _limit_of())
    shut = [e.well for e in decision.decisions if e.kind is EventKind.SHUT]
    assert "41" in shut

    _rest, _before, after = watercut_cap_shutins(
        state, scoped, decision.decisions, ("41", "42", "43"), 0.9
    )
    assert after <= 0.9


def test_disabled_feature_reproduces_the_previous_decision_bit_for_bit(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _watercut_context(context, 0.9)
    theta = default_theta()
    off = decide_group(state, scoped, theta, _r0_only(), _limit_of())
    no_limit = decide_group(
        state, _watercut_context(context, None), theta, _r0_only(), _limit_of()
    )
    assert off.decisions == no_limit.decisions
    assert [e.entry.decision for e in off.trace] == [
        e.entry.decision for e in no_limit.trace
    ]
    assert not [
        e for e in off.trace if e.entry.decision == "SHUT_TO_WATERCUT_LIMIT"
    ]


def _floor_context(context: RuleContext, floors: dict[int, float]) -> RuleContext:
    return replace(
        context,
        constraints=Constraints(production_floors=floors),
        groups=groups_of({"G1": ("41", "42", "43")}),
    )


def test_report_says_not_attempted_when_no_floor_is_declared(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    check = check_production_floor(
        state, _floor_context(context, {}), (), ("41", "42", "43"), None
    )
    assert check.status == PRODUCTION_FLOOR_NOT_SET
    assert check.attempted is False
    assert check.unreachable is False
    with pytest.raises(ValueError):
        check.as_entry(0, "G1")


def test_report_says_unreachable_when_the_prediction_misses_the_floor(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _floor_context(context, {2010: 100_000.0})
    check = check_production_floor(state, scoped, (), ("41", "42", "43"), None)
    assert check.status == PRODUCTION_FLOOR_UNREACHABLE
    assert check.attempted is True
    assert check.unreachable is True

    entry = check.as_entry(0, "G1")
    assert entry.decision == PRODUCTION_FLOOR_UNREACHABLE
    assert entry.inputs["production_floor_shortfall_t_per_day"] > 0.0


def test_report_says_met_when_the_prediction_clears_the_floor(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _floor_context(context, {2010: 0.5})
    check = check_production_floor(state, scoped, (), ("41", "42", "43"), None)
    assert check.status == PRODUCTION_FLOOR_MET
    assert check.attempted is True
    assert check.unreachable is False


def test_report_distinguishes_not_met_from_not_attempted(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    missed = check_production_floor(
        state, _floor_context(context, {2010: 100_000.0}), (), ("41", "42", "43"), None
    )
    silent = check_production_floor(
        state, _floor_context(context, {}), (), ("41", "42", "43"), None
    )
    assert missed.status != silent.status
    assert missed.attempted and not silent.attempted
    assert missed.predicted_t_per_day is not None
    assert silent.predicted_t_per_day is None


def test_unreachable_floor_reaches_the_group_trace(context: RuleContext) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _floor_context(context, {2010: 100_000.0})
    decision = decide_group(
        state, scoped, default_theta(), _r0_only(), _limit_of()
    )
    decisions = [e.entry.decision for e in decision.trace]
    assert PRODUCTION_FLOOR_UNREACHABLE in decisions


def test_absent_floor_leaves_no_record_in_the_group_trace(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _floor_context(context, {})
    decision = decide_group(
        state, scoped, default_theta(), _r0_only(), _limit_of()
    )
    decisions = [e.entry.decision for e in decision.trace]
    assert PRODUCTION_FLOOR_UNREACHABLE not in decisions
    assert PRODUCTION_FLOOR_NOT_SET not in decisions


def test_shut_wells_do_not_count_toward_the_predicted_floor(
    context: RuleContext,
) -> None:
    state = state_of(*WATERCUT_WELLS)
    scoped = _floor_context(context, {2010: 0.5})
    full = check_production_floor(state, scoped, (), ("41", "42", "43"), None)
    flags = _r0_only().with_feature(WATERCUT_CAP_FEATURE, True)
    watered = replace(
        scoped,
        constraints=Constraints(
            production_floors={2010: 0.5}, watercut_limits={2010: 0.9}
        ),
    )
    decision = decide_group(state, watered, default_theta(), flags, _limit_of())
    after = check_production_floor(
        state, scoped, decision.decisions, ("41", "42", "43"), None
    )
    assert full.predicted_t_per_day is not None
    assert after.predicted_t_per_day is not None
    assert after.predicted_t_per_day < full.predicted_t_per_day


def test_oil_density_is_the_conftest_value(context: RuleContext) -> None:
    assert context.oil_density_t_per_m3 == OIL_DENSITY_T_PER_M3
