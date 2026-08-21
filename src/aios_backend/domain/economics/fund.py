from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from aios_backend.core.contracts import (
    IntervalResponse,
    NormativeSet,
    StateAtDate,
    is_excluded_by_negative_rule,
)


class FundState(Enum):
    NOT_COMMISSIONED = "NOT_COMMISSIONED"
    PROD_ACTIVE = "PROD_ACTIVE"
    INJ_ACTIVE = "INJ_ACTIVE"
    SHUT = "SHUT"


ACTIVE_FUND_STATES: frozenset[FundState] = frozenset(
    {FundState.PROD_ACTIVE, FundState.INJ_ACTIVE}
)


@dataclass(frozen=True, slots=True)
class FundTransition:
    control_step: int
    well: str
    previous: FundState
    current: FundState
    event_cost_rub: float
    conversion_opex_rub: float


@dataclass(frozen=True, slots=True)
class WellFundTrack:
    well: str
    state_by_control_step: dict[int, FundState]
    active_by_control_step: dict[int, bool]
    transitions: tuple[FundTransition, ...]
    event_costs_by_control_step: dict[int, float]


def classify_fund_state(state: StateAtDate, seen_active: bool) -> FundState:
    if state.liquid_rate > 0 and state.injection_rate > 0:
        raise ValueError(
            f"скважина {state.well}, deck_step={state.deck_date_index}: "
            "одновременно WLPR > 0 и WWIR > 0, роль не определяется"
        )
    if state.liquid_rate > 0:
        return FundState.PROD_ACTIVE
    if state.injection_rate > 0:
        return FundState.INJ_ACTIVE
    if seen_active:
        return FundState.SHUT
    return FundState.NOT_COMMISSIONED


def transition_costs(
    previous: FundState, current: FundState, normatives: NormativeSet
) -> tuple[float, float]:
    if previous is current:
        return 0.0, 0.0
    if current is FundState.NOT_COMMISSIONED:
        raise ValueError(f"переход {previous.value} → NOT_COMMISSIONED невозможен")
    if previous is FundState.NOT_COMMISSIONED:
        if current in ACTIVE_FUND_STATES:
            return normatives.event_cost_rub, 0.0
        raise ValueError("переход NOT_COMMISSIONED → SHUT невозможен")
    if previous is FundState.PROD_ACTIVE and current is FundState.INJ_ACTIVE:
        return 0.0, normatives.conversion_base_cost_rub
    if previous is FundState.INJ_ACTIVE and current is FundState.PROD_ACTIVE:
        raise ValueError(
            "переход INJ_ACTIVE → PROD_ACTIVE Методикой не определён"
        )
    return normatives.event_cost_rub, 0.0


def track_well(
    well: str,
    states_by_deck_step: Sequence[StateAtDate],
    responses_by_control_step: Sequence[IntervalResponse],
    normatives: NormativeSet,
) -> WellFundTrack:
    n_deck_dates = len(states_by_deck_step)
    n_intervals = len(responses_by_control_step)
    if n_intervals == 0:
        raise ValueError(f"скважина {well}: пустой ряд IntervalResponse")
    if n_deck_dates <= n_intervals:
        raise ValueError(
            f"скважина {well}: дат дека {n_deck_dates} — не больше числа "
            f"интервалов {n_intervals}, истории нет"
        )
    for deck_step, state in enumerate(states_by_deck_step):
        if state.well != well:
            raise ValueError(
                f"скважина {well}: StateAtDate на позиции {deck_step} "
                f"принадлежит {state.well}"
            )
        if state.deck_date_index != deck_step:
            raise ValueError(
                f"скважина {well}: deck_date_index={state.deck_date_index} "
                f"на позиции {deck_step}, ряд не плотный"
            )
    for control_step, response in enumerate(responses_by_control_step):
        if response.well != well:
            raise ValueError(
                f"скважина {well}: IntervalResponse на позиции {control_step} "
                f"принадлежит {response.well}"
            )
        if response.control_step != control_step:
            raise ValueError(
                f"скважина {well}: control_step={response.control_step} "
                f"на позиции {control_step}, ряд не плотный"
            )

    first_interval_end_deck_step = n_deck_dates - n_intervals
    seen_active = False
    current = FundState.NOT_COMMISSIONED
    for deck_step in range(first_interval_end_deck_step):
        current = classify_fund_state(states_by_deck_step[deck_step], seen_active)
        seen_active = seen_active or current in ACTIVE_FUND_STATES

    state_by_control_step: dict[int, FundState] = {}
    active_by_control_step: dict[int, bool] = {}
    event_costs_by_control_step: dict[int, float] = {}
    transitions: list[FundTransition] = []
    for control_step in range(n_intervals):
        response = responses_by_control_step[control_step]
        if is_excluded_by_negative_rule(response):
            continue
        observed = classify_fund_state(
            states_by_deck_step[first_interval_end_deck_step + control_step],
            seen_active,
        )
        event_cost_rub, conversion_opex_rub = transition_costs(
            current, observed, normatives
        )
        if observed is not current:
            transitions.append(
                FundTransition(
                    control_step=control_step,
                    well=well,
                    previous=current,
                    current=observed,
                    event_cost_rub=event_cost_rub,
                    conversion_opex_rub=conversion_opex_rub,
                )
            )
        state_by_control_step[control_step] = observed
        active_by_control_step[control_step] = observed in ACTIVE_FUND_STATES
        event_costs_by_control_step[control_step] = (
            event_cost_rub + conversion_opex_rub
        )
        current = observed
        seen_active = seen_active or observed in ACTIVE_FUND_STATES

    return WellFundTrack(
        well=well,
        state_by_control_step=state_by_control_step,
        active_by_control_step=active_by_control_step,
        transitions=tuple(transitions),
        event_costs_by_control_step=event_costs_by_control_step,
    )
