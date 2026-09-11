from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.economics.domain.esp import EspStateMachine, pick_initial_esp
from backend.contexts.economics.domain.fund import FundState, classify_fund_state, track_well
from backend.contexts.reservoir.domain.response import (
    ActiveControlMode,
    IntervalResponse,
    StateAtDate,
    is_excluded_by_negative_rule,
)
from backend.contexts.surrogate.domain.errors import MetricsError


@dataclass(frozen=True, slots=True)
class WellTrajectory:
    well: str
    states: tuple[StateAtDate, ...]
    responses: tuple[IntervalResponse, ...]

    def __post_init__(self) -> None:
        if not self.states or not self.responses:
            raise MetricsError(f"well {self.well}: empty trajectory")
        if len(self.states) <= len(self.responses):
            raise MetricsError(
                f"well {self.well}: {len(self.states)} deck dates, not more than "
                f"the interval count {len(self.responses)}, so there is no history"
            )

    @property
    def first_interval_end_deck_step(self) -> int:
        return len(self.states) - len(self.responses)

    def excluded_deck_steps(self) -> frozenset[int]:
        shift = self.first_interval_end_deck_step
        return frozenset(
            shift + response.control_step
            for response in self.responses
            if is_excluded_by_negative_rule(response)
        )


@dataclass(frozen=True, slots=True)
class StateMetrics:
    n_states: int
    active_shut_accuracy: float
    fund_state_accuracy: float
    transition_precision: float
    transition_recall: float
    esp_nominal_accuracy: float
    esp_capex_absolute_error_rub: float
    esp_capex_signed_error_rub: float
    event_cost_absolute_error_rub: float
    event_cost_signed_error_rub: float
    bhp_limited_accuracy: float
    bhp_limited_f1: float
    bhp_mae_bar: float

    @property
    def money_absolute_error_rub(self) -> float:
        return self.esp_capex_absolute_error_rub + self.event_cost_absolute_error_rub


def _paired(
    predicted: Sequence[WellTrajectory], actual: Sequence[WellTrajectory]
) -> list[tuple[WellTrajectory, WellTrajectory]]:
    by_well = {track.well: track for track in actual}
    if len(by_well) != len(actual):
        raise MetricsError("a well occurs twice in the actual trajectories")
    pairs: list[tuple[WellTrajectory, WellTrajectory]] = []
    for model in predicted:
        fact = by_well.get(model.well)
        if fact is None:
            raise MetricsError(f"well {model.well} is missing from the actual trajectories")
        if len(model.states) != len(fact.states):
            raise MetricsError(
                f"well {model.well}: {len(model.states)} deck dates against {len(fact.states)}"
            )
        pairs.append((model, fact))
    if not pairs:
        raise MetricsError("there is not a single pair of trajectories")
    return pairs


def f1_score(true_positive: int, false_positive: int, false_negative: int) -> float:
    if true_positive == 0:
        return 0.0
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    return 2.0 * precision * recall / (precision + recall)


def state_metrics(
    predicted: Sequence[WellTrajectory],
    actual: Sequence[WellTrajectory],
    *,
    normatives: NormativeSet,
    policies: Policies,
) -> StateMetrics:
    pairs = _paired(predicted, actual)
    machine = EspStateMachine(normatives, policies.charge_initial_esp)
    catalog = tuple(sorted(normatives.esp_catalog, key=lambda entry: entry.nominal))

    n_states = 0
    active_hits = 0
    fund_hits = 0
    esp_hits = 0
    esp_comparisons = 0
    bhp_absolute_error = 0.0
    true_positive = false_positive = false_negative = true_negative = 0
    esp_capex_signed = 0.0
    esp_capex_absolute = 0.0
    event_signed = 0.0
    event_absolute = 0.0
    matched_transitions = 0
    predicted_transitions = 0
    actual_transitions = 0

    for model, fact in pairs:
        model_seen_active = False
        fact_seen_active = False
        for model_state, fact_state in zip(model.states, fact.states):
            if model_state.deck_date_index != fact_state.deck_date_index:
                raise MetricsError(
                    f"well {model.well}: date axes diverged "
                    f"({model_state.deck_date_index} against {fact_state.deck_date_index})"
                )
            n_states += 1

            model_fund = classify_fund_state(model_state, model_seen_active)
            fact_fund = classify_fund_state(fact_state, fact_seen_active)
            model_seen_active = model_seen_active or model_fund in (
                FundState.PROD_ACTIVE,
                FundState.INJ_ACTIVE,
            )
            fact_seen_active = fact_seen_active or fact_fund in (
                FundState.PROD_ACTIVE,
                FundState.INJ_ACTIVE,
            )

            if model_fund is fact_fund:
                fund_hits += 1
            model_active = model_fund in (FundState.PROD_ACTIVE, FundState.INJ_ACTIVE)
            fact_active = fact_fund in (FundState.PROD_ACTIVE, FundState.INJ_ACTIVE)
            if model_active == fact_active:
                active_hits += 1

            if fact_active and fact_fund is FundState.PROD_ACTIVE:
                esp_comparisons += 1
                model_pick = pick_initial_esp(model_state.liquid_rate, catalog)
                fact_pick = pick_initial_esp(fact_state.liquid_rate, catalog)
                if model_pick.nominal == fact_pick.nominal:
                    esp_hits += 1

            model_limited = model_state.active_control_mode is ActiveControlMode.BHP_LIMITED
            fact_limited = fact_state.active_control_mode is ActiveControlMode.BHP_LIMITED
            if model_limited and fact_limited:
                true_positive += 1
            elif model_limited and not fact_limited:
                false_positive += 1
            elif fact_limited:
                false_negative += 1
            else:
                true_negative += 1

            bhp_absolute_error += abs(model_state.bhp - fact_state.bhp)

        model_fund_track = track_well(
            model.well, model.states, model.responses, normatives
        )
        fact_fund_track = track_well(fact.well, fact.states, fact.responses, normatives)

        model_keys = {
            (transition.control_step, transition.previous, transition.current)
            for transition in model_fund_track.transitions
        }
        fact_keys = {
            (transition.control_step, transition.previous, transition.current)
            for transition in fact_fund_track.transitions
        }
        matched_transitions += len(model_keys & fact_keys)
        predicted_transitions += len(model_keys)
        actual_transitions += len(fact_keys)

        model_events = sum(
            transition.event_cost_rub + transition.conversion_opex_rub
            for transition in model_fund_track.transitions
        )
        fact_events = sum(
            transition.event_cost_rub + transition.conversion_opex_rub
            for transition in fact_fund_track.transitions
        )
        event_signed += model_events - fact_events
        event_absolute += abs(model_events - fact_events)

        model_esp = machine.track_well(
            model.well, model.states, len(model.responses), model.excluded_deck_steps()
        )
        fact_esp = machine.track_well(
            fact.well, fact.states, len(fact.responses), fact.excluded_deck_steps()
        )
        model_money = model_esp.total_capex_rub + model_esp.total_opex_rub
        fact_money = fact_esp.total_capex_rub + fact_esp.total_opex_rub
        esp_capex_signed += model_money - fact_money
        esp_capex_absolute += abs(model_money - fact_money)

    return StateMetrics(
        n_states=n_states,
        active_shut_accuracy=active_hits / n_states,
        fund_state_accuracy=fund_hits / n_states,
        transition_precision=(
            matched_transitions / predicted_transitions if predicted_transitions else 1.0
        ),
        transition_recall=(
            matched_transitions / actual_transitions if actual_transitions else 1.0
        ),
        esp_nominal_accuracy=(esp_hits / esp_comparisons if esp_comparisons else 1.0),
        esp_capex_absolute_error_rub=esp_capex_absolute,
        esp_capex_signed_error_rub=esp_capex_signed,
        event_cost_absolute_error_rub=event_absolute,
        event_cost_signed_error_rub=event_signed,
        bhp_limited_accuracy=(true_positive + true_negative) / n_states,
        bhp_limited_f1=f1_score(true_positive, false_positive, false_negative),
        bhp_mae_bar=bhp_absolute_error / n_states,
    )


__all__ = [
    "StateMetrics",
    "WellTrajectory",
    "state_metrics",
]
