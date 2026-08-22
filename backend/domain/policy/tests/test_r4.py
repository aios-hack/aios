from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core.contracts import EventKind, Rule

from backend.domain.policy import (
    RuleContext,
    RuleFlags,
    WellMemory,
    apply_rule,
    default_theta,
    esp_size_for,
    esp_upgrade_cost_rub,
)
from backend.domain.policy.rules import r4
from backend.domain.policy.tests.conftest import ESP_CATALOG, memory_of, producer, state_of

CLEAN = 0.30
VERY_WET = 0.985


def outcome_of(context: RuleContext, wells, memory=None):
    ctx = replace(context, memory=memory if memory is not None else memory_of())
    return r4.apply(state_of(*wells), ctx, default_theta())


def test_rule_states_its_criterion_in_field_language() -> None:
    assert r4.ADMISSION_CRITERION.endswith(".")
    assert len(r4.ADMISSION_CRITERION.split()) <= 20


def test_r4_spends_no_theta() -> None:
    assert r4.THETA_NAMES == ()


def test_esp_size_comes_from_the_catalog_not_from_a_literal() -> None:
    assert esp_size_for(ESP_CATALOG, 30.0).nominal == 45.0
    assert esp_size_for(ESP_CATALOG, 100.0).nominal == 125.0
    with pytest.raises(ValueError, match="каталог"):
        esp_size_for((), 30.0)


def test_the_ratchet_never_lets_the_size_go_down() -> None:
    installed = WellMemory(esp_nominal_m3_per_day=80.0)
    assert installed.with_esp(125.0).esp_nominal_m3_per_day == 125.0
    with pytest.raises(ValueError, match="не понижается"):
        installed.with_esp(45.0)


def test_a_wet_speedup_that_does_not_pay_for_the_pump_is_capped(
    context: RuleContext,
) -> None:
    wells = (producer("42", 40.0, VERY_WET, setpoint=120.0),)
    memory = memory_of(**{"42": WellMemory(esp_nominal_m3_per_day=45.0)})
    outcome = outcome_of(context, wells, memory)
    assert [d.kind for d in outcome.decisions] == [EventKind.SET_LRAT]
    assert outcome.decisions[0].value <= 45.0
    assert [e.decision for e in outcome.trace] == ["CAP_AT_ESP_SIZE"]


def test_a_clean_speedup_that_pays_for_the_pump_is_allowed(
    context: RuleContext,
) -> None:
    wells = (producer("42", 40.0, CLEAN, setpoint=120.0),)
    memory = memory_of(**{"42": WellMemory(esp_nominal_m3_per_day=45.0)})
    outcome = outcome_of(context, wells, memory)
    assert outcome.decisions == ()
    assert [e.decision for e in outcome.trace] == ["ALLOW_UPSIZE"]


def test_the_trace_carries_the_capex_and_the_gain(context: RuleContext) -> None:
    wells = (producer("42", 40.0, VERY_WET, setpoint=120.0),)
    memory = memory_of(**{"42": WellMemory(esp_nominal_m3_per_day=45.0)})
    entry = outcome_of(context, wells, memory).trace[0]
    assert entry.inputs["upgrade_cost_rub"] > 0.0
    assert entry.inputs["esp_swap_opex_rub"] == (
        context.normatives.esp_swap_opex_rub
    )
    assert entry.inputs["installed_esp_nominal_m3_per_day"] == 45.0
    assert entry.inputs["needed_esp_nominal_m3_per_day"] > 45.0
    assert "annual_gain_rub" in entry.inputs
    assert "payback_years" in entry.inputs


def test_a_speedup_inside_the_installed_size_is_untouched(
    context: RuleContext,
) -> None:
    wells = (producer("42", 40.0, VERY_WET, setpoint=50.0),)
    memory = memory_of(**{"42": WellMemory(esp_nominal_m3_per_day=125.0)})
    outcome = outcome_of(context, wells, memory)
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_slowing_down_never_triggers_the_rule(context: RuleContext) -> None:
    wells = (producer("42", 40.0, VERY_WET, setpoint=20.0),)
    memory = memory_of(**{"42": WellMemory(esp_nominal_m3_per_day=45.0)})
    outcome = outcome_of(context, wells, memory)
    assert outcome.decisions == ()
    assert outcome.trace == ()


def test_upgrade_cost_is_pump_plus_swap_operation() -> None:
    target = esp_size_for(ESP_CATALOG, 100.0)
    cost = esp_upgrade_cost_rub(45.0, target, 1_800_000.0)
    assert cost == target.cost_rub + 1_800_000.0
    assert esp_upgrade_cost_rub(125.0, target, 1_800_000.0) == 0.0


def test_disabled_r4_makes_no_decisions_and_no_records(
    context: RuleContext,
) -> None:
    wells = (producer("42", 40.0, VERY_WET, setpoint=120.0),)
    ctx = replace(
        context, memory=memory_of(**{"42": WellMemory(esp_nominal_m3_per_day=45.0)})
    )
    off = apply_rule(
        Rule.R4,
        state_of(*wells),
        ctx,
        default_theta(),
        RuleFlags().with_disabled(Rule.R4),
    )
    assert off.decisions == ()
    assert off.trace == ()
