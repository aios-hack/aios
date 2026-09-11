
from __future__ import annotations

from backend.contexts.surrogate.domain.errors import (
    MetricsError,
)

from collections.abc import Sequence
from dataclasses import dataclass

from backend.core.contracts import (
    ActiveControlMode,
    IntervalResponse,
    NormativeSet,
    Policies,
    StateAtDate,
    is_excluded_by_negative_rule,
    watercut,
)

from backend.contexts.economics.domain.esp import EspStateMachine, pick_initial_esp
from backend.contexts.economics.domain.fund import FundState, classify_fund_state, track_well
from backend.contexts.surrogate.domain.crm import spearman


@dataclass(frozen=True, slots=True)
class NpvRankingMetrics:
    n_candidates: int
    spearman_rank_correlation: float
    precision_at_k: dict[int, float]
    regret_at_k_rub: dict[int, float]

    def __post_init__(self) -> None:
        if self.n_candidates < 2:
            raise MetricsError(
                f"ранжирование на {self.n_candidates} кандидатах не определено"
            )


def _top_k_indices(values: Sequence[float], k: int) -> list[int]:
    return sorted(range(len(values)), key=lambda i: (-values[i], i))[:k]


def ranking_metrics(
    actual_npv: Sequence[float],
    predicted_npv: Sequence[float],
    *,
    k_values: Sequence[int] = (1, 3, 5),
) -> NpvRankingMetrics:
    if len(actual_npv) != len(predicted_npv):
        raise MetricsError(
            f"кандидатов {len(actual_npv)} по факту и {len(predicted_npv)} по прогнозу"
        )
    n = len(actual_npv)
    if n < 2:
        raise MetricsError(f"ранжирование на {n} кандидатах не определено")

    precision: dict[int, float] = {}
    regret: dict[int, float] = {}
    best_actual = max(actual_npv)

    for k in k_values:
        if k < 1:
            raise MetricsError(f"k={k} < 1")
        if k > n:
            continue
        predicted_top = _top_k_indices(predicted_npv, k)
        actual_top = set(_top_k_indices(actual_npv, k))
        precision[k] = len(set(predicted_top) & actual_top) / k
        regret[k] = best_actual - max(actual_npv[i] for i in predicted_top)

    if not precision:
        raise MetricsError(f"ни одно k из {tuple(k_values)} не помещается в {n} кандидатов")

    return NpvRankingMetrics(
        n_candidates=n,
        spearman_rank_correlation=spearman(actual_npv, predicted_npv),
        precision_at_k=precision,
        regret_at_k_rub=regret,
    )


@dataclass(frozen=True, slots=True)
class WatercutMetrics:
    n_points: int
    mae: float
    median_absolute_error: float
    share_of_drops: float


def watercut_metrics(
    actual: Sequence[IntervalResponse],
    predicted: Sequence[IntervalResponse],
    *,
    oil_density_t_per_m3: float,
) -> WatercutMetrics:
    if len(actual) != len(predicted):
        raise MetricsError("ряды отклика разной длины")

    errors: list[float] = []
    predicted_series: list[float] = []
    for fact, model in zip(actual, predicted):
        if fact.control_step != model.control_step or fact.well != model.well:
            raise MetricsError(
                f"пара не совпала по оси: факт ({fact.control_step}, {fact.well}), "
                f"прогноз ({model.control_step}, {model.well})"
            )
        if fact.liquid_volume_delta == 0.0 or model.liquid_volume_delta == 0.0:
            continue
        fact_value = watercut(fact, oil_density_t_per_m3)
        model_value = watercut(model, oil_density_t_per_m3)
        errors.append(abs(fact_value - model_value))
        predicted_series.append(model_value)

    if not errors:
        raise MetricsError("обводнённость не определена ни на одном интервале")

    drops = sum(
        1
        for previous, current in zip(predicted_series, predicted_series[1:])
        if current < previous
    )
    comparisons = max(1, len(predicted_series) - 1)
    ordered = sorted(errors)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2 == 1
        else 0.5 * (ordered[middle - 1] + ordered[middle])
    )

    return WatercutMetrics(
        n_points=len(errors),
        mae=sum(errors) / len(errors),
        median_absolute_error=median,
        share_of_drops=drops / comparisons,
    )


@dataclass(frozen=True, slots=True)
class WellTrajectory:
    well: str
    states: tuple[StateAtDate, ...]
    responses: tuple[IntervalResponse, ...]

    def __post_init__(self) -> None:
        if not self.states or not self.responses:
            raise MetricsError(f"скважина {self.well}: пустая траектория")
        if len(self.states) <= len(self.responses):
            raise MetricsError(
                f"скважина {self.well}: дат дека {len(self.states)} — не больше "
                f"числа интервалов {len(self.responses)}, истории нет"
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
        raise MetricsError("в фактических траекториях скважина встречается дважды")
    pairs: list[tuple[WellTrajectory, WellTrajectory]] = []
    for model in predicted:
        fact = by_well.get(model.well)
        if fact is None:
            raise MetricsError(f"скважины {model.well} нет среди фактических траекторий")
        if len(model.states) != len(fact.states):
            raise MetricsError(
                f"скважина {model.well}: дат дека {len(model.states)} против {len(fact.states)}"
            )
        pairs.append((model, fact))
    if not pairs:
        raise MetricsError("нет ни одной пары траекторий")
    return pairs


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
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
                    f"скважина {model.well}: оси дат разошлись "
                    f"({model_state.deck_date_index} против {fact_state.deck_date_index})"
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
        bhp_limited_f1=_f1(true_positive, false_positive, false_negative),
        bhp_mae_bar=bhp_absolute_error / n_states,
    )


@dataclass(frozen=True, slots=True)
class SurrogateMetrics:
    ranking: NpvRankingMetrics
    state: StateMetrics
    watercut: WatercutMetrics
    synthetic_inputs: bool = False


@dataclass(frozen=True, slots=True)
class AcceptanceVerdict:
    accepted: bool
    model_spearman: float
    baseline_spearman: float
    reason: str

    @property
    def margin(self) -> float:
        return self.model_spearman - self.baseline_spearman


def accept_against_baseline(
    model: NpvRankingMetrics,
    baseline: NpvRankingMetrics,
    *,
    synthetic_inputs: bool = False,
) -> AcceptanceVerdict:
    if model.n_candidates != baseline.n_candidates:
        raise MetricsError(
            f"сравнение на разных выборках: {model.n_candidates} против "
            f"{baseline.n_candidates} кандидатов"
        )
    if synthetic_inputs:
        return AcceptanceVerdict(
            accepted=False,
            model_spearman=model.spearman_rank_correlation,
            baseline_spearman=baseline.spearman_rank_correlation,
            reason=(
                "метрики посчитаны на синтетике: правило 4 запрещает предъявлять "
                "их как замер качества, вердикт не выносится"
            ),
        )

    margin = model.spearman_rank_correlation - baseline.spearman_rank_correlation
    if margin > 0.0:
        return AcceptanceVerdict(
            accepted=True,
            model_spearman=model.spearman_rank_correlation,
            baseline_spearman=baseline.spearman_rank_correlation,
            reason=(
                f"ранговая корреляция {model.spearman_rank_correlation:.4f} выше "
                f"базовой линии CRM {baseline.spearman_rank_correlation:.4f} "
                f"на {margin:.4f}"
            ),
        )
    return AcceptanceVerdict(
        accepted=False,
        model_spearman=model.spearman_rank_correlation,
        baseline_spearman=baseline.spearman_rank_correlation,
        reason=(
            f"ранговая корреляция {model.spearman_rank_correlation:.4f} не выше "
            f"базовой линии CRM {baseline.spearman_rank_correlation:.4f}: "
            f"модель отвергается (§5.5)"
        ),
    )
