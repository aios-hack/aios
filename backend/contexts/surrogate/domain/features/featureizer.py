from __future__ import annotations

import math
from datetime import date
from typing import Mapping, Sequence

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.schedule.domain.schedule import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
)
from backend.contexts.schedule.domain.wcon import commissioning_state
from backend.contexts.surrogate.domain.errors import FeatureError
from backend.contexts.surrogate.domain.features.types import (
    FeatureContext,
    LambdaEdgeFeature,
    SurrogateInput,
    WellStepFeatures,
    _EVENT_ORDER,
    _MutableState,
)
from backend.shared.hashing import hash_schedule


def _commissioning_state(event_operator: str, raw_args: tuple[str, ...]) -> _MutableState:
    try:
        return _MutableState.from_contract(commissioning_state(event_operator, raw_args))
    except ValueError as error:
        raise FeatureError(str(error)) from error


def _apply_control(state: _MutableState, event: ControlEvent) -> None:
    if state.availability is Availability.NOT_COMMISSIONED:
        raise FeatureError(
            f"control_step={event.control_step}, well={event.well!r}: control before commissioning"
        )
    if event.kind is EventKind.CONVERT_INJ:
        if state.role is not Role.PROD:
            raise FeatureError(f"{event.well!r}: CONVERT_INJ applied to a non-PROD well")
        state.role = Role.INJ
    elif event.kind is EventKind.SET_LRAT:
        if state.role is not Role.PROD:
            raise FeatureError(f"{event.well!r}: SET_LRAT applied to a non-PROD well")
        state.setpoint = event.value if event.value is not None else 0.0
    elif event.kind is EventKind.SET_RATE:
        if state.role is not Role.INJ:
            raise FeatureError(f"{event.well!r}: SET_RATE applied to a non-INJ well")
        state.setpoint = event.value if event.value is not None else 0.0
    elif event.kind is EventKind.OPEN:
        state.operating_status = OperatingStatus.OPEN
    elif event.kind is EventKind.SHUT:
        state.operating_status = OperatingStatus.SHUT


class ScheduleFeatureizer:
    def transform(self, schedule: Schedule, context: FeatureContext) -> SurrogateInput:
        wells = tuple(schedule.meta.wells)
        if not wells or len(set(wells)) != len(wells):
            raise FeatureError("Schedule.meta.wells must be a non-empty axis without duplicates")
        if set(schedule.initial_state) != set(wells):
            raise FeatureError("initial_state must contain exactly Schedule.meta.wells")
        if len(context.control_dates) != schedule.meta.n_control_dates:
            raise FeatureError(
                "control_dates must contain n_control_dates dates, including terminal_state"
            )
        if context.control_dates[0] != schedule.meta.t0:
            raise FeatureError("control_dates[0] does not match Schedule.meta.t0")
        if any(right <= left for left, right in zip(context.control_dates, context.control_dates[1:])):
            raise FeatureError("control_dates must be strictly increasing")
        if context.history_start != date(1994, 11, 1):
            raise FeatureError("Model_Z cumulative targets must start on 1994-11-01")
        if context.history_prefix_hash != schedule.meta.history_prefix_hash:
            raise FeatureError("history_targets were not built from a prefix of this Schedule")
        if set(context.history_targets) != set(wells):
            raise FeatureError("history_targets must contain exactly Schedule.meta.wells")
        if set(context.static_features) != set(wells):
            raise FeatureError("static_features must contain exactly Schedule.meta.wells")

        static_names = tuple(sorted(context.static_features[wells[0]]))
        static_values: dict[str, tuple[float, ...]] = {}
        for well in wells:
            values = context.static_features[well]
            if tuple(sorted(values)) != static_names:
                raise FeatureError("the static feature set must be the same for every well")
            row = tuple(float(values[name]) for name in static_names)
            if not all(math.isfinite(value) for value in row):
                raise FeatureError(f"non-numeric static features for well {well!r}")
            static_values[well] = row

        states = {well: _MutableState.from_contract(schedule.initial_state[well]) for well in wells}
        liquid = {
            well: context.history_targets[well].target_liquid_m3 for well in wells
        }
        injection = {
            well: context.history_targets[well].target_injection_m3 for well in wells
        }
        event_count = {well: context.history_targets[well].event_count for well in wells}
        fixed_event_count = {well: 0 for well in wells}

        fixed_by_step: dict[int, list] = {}
        for event in schedule.fixed_deck_events:
            if event.well not in states:
                raise FeatureError(f"unknown well in fixed_deck_events: {event.well!r}")
            fixed_by_step.setdefault(event.control_step, []).append(event)
        controls_by_step: dict[int, list[ControlEvent]] = {}
        for event in schedule.control_events:
            if event.well not in states:
                raise FeatureError(f"unknown well in control_events: {event.well!r}")
            controls_by_step.setdefault(event.control_step, []).append(event)

        nodes: list[WellStepFeatures] = []
        edges: list[LambdaEdgeFeature] = []
        for control_step in range(schedule.meta.n_intervals):
            interval_start = context.control_dates[control_step]
            interval_end = context.control_dates[control_step + 1]
            lambda_ = self._lambda_for_date(context.lambda_windows, interval_start)
            self._validate_lambda(lambda_, wells)

            for event in fixed_by_step.get(control_step, ()):
                fixed_event_count[event.well] += 1
                if event.operator in {"WCONPROD", "WCONINJE"}:
                    if states[event.well].availability is Availability.AVAILABLE:
                        raise FeatureError(f"repeated commissioning of well {event.well!r}")
                    states[event.well] = _commissioning_state(event.operator, event.raw_args)
                    event_count[event.well] += 1

            ordered_controls = sorted(
                controls_by_step.get(control_step, ()),
                key=lambda event: (event.well, _EVENT_ORDER[event.kind]),
            )
            for event in ordered_controls:
                _apply_control(states[event.well], event)
                event_count[event.well] += 1

            days = (interval_end - interval_start).days
            for well, state in states.items():
                volume = state.effective_target * days
                if state.role is Role.PROD:
                    liquid[well] += volume
                elif state.role is Role.INJ:
                    injection[well] += volume

            edge_rows: dict[str, list[LambdaEdgeFeature]] = {}
            for producer_index, producer in enumerate(lambda_.producers):
                if (
                    states[producer].availability is Availability.NOT_COMMISSIONED
                    or states[producer].role is not Role.PROD
                ):
                    continue
                for injector_index, injector in enumerate(lambda_.injectors):
                    if (
                        states[injector].availability is Availability.NOT_COMMISSIONED
                        or states[injector].role is not Role.INJ
                    ):
                        continue
                    coefficient = float(lambda_.matrix[producer_index][injector_index])
                    injector_rate = (
                        states[injector].effective_target
                        if states[injector].role is Role.INJ
                        else 0.0
                    )
                    edge = LambdaEdgeFeature(
                        control_step=control_step,
                        producer=producer,
                        injector=injector,
                        coefficient=coefficient,
                        injector_target_rate_m3_per_day=injector_rate,
                        injector_cumulative_target_injection_m3=injection[injector],
                        weighted_target_rate_m3_per_day=coefficient * injector_rate,
                        weighted_cumulative_target_injection_m3=(
                            coefficient * injection[injector]
                        ),
                    )
                    edges.append(edge)
                    edge_rows.setdefault(producer, []).append(edge)

            for well in wells:
                state = states[well]
                neighbor_edges = edge_rows.get(well, ())
                nodes.append(
                    WellStepFeatures(
                        control_step=control_step,
                        interval_start=interval_start,
                        interval_end=interval_end,
                        well=well,
                        availability=state.availability,
                        role=state.role,
                        operating_status=state.operating_status,
                        setpoint_m3_per_day=state.setpoint,
                        effective_target_rate_m3_per_day=state.effective_target,
                        cumulative_target_liquid_m3=liquid[well],
                        cumulative_target_injection_m3=injection[well],
                        cumulative_neighbor_injection_m3=sum(
                            edge.weighted_cumulative_target_injection_m3
                            for edge in neighbor_edges
                        ),
                        current_neighbor_injection_m3_per_day=sum(
                            edge.weighted_target_rate_m3_per_day for edge in neighbor_edges
                        ),
                        event_count=event_count[well],
                        fixed_event_count=fixed_event_count[well],
                        static_values=static_values[well],
                        lambda_window_start=lambda_.window_start,
                        lambda_window_end=lambda_.window_end,
                    )
                )

        return SurrogateInput(
            canonical_schedule_hash=hash_schedule(schedule),
            wells=wells,
            static_feature_names=static_names,
            nodes=tuple(nodes),
            lambda_edges=tuple(edges),
        )

    @staticmethod
    def _lambda_for_date(windows: Sequence[Lambda], on_date: date) -> Lambda:
        matches = [
            lambda_
            for lambda_ in windows
            if lambda_.window_start <= on_date <= lambda_.window_end
        ]
        if len(matches) != 1:
            raise FeatureError(
                f"exactly one lambda window was expected for {on_date.isoformat()}, found {len(matches)}"
            )
        return matches[0]

    @staticmethod
    def _validate_lambda(lambda_: Lambda, wells: tuple[str, ...]) -> None:
        if len(set(lambda_.producers)) != len(lambda_.producers):
            raise FeatureError("lambda.producers contains duplicates")
        if len(set(lambda_.injectors)) != len(lambda_.injectors):
            raise FeatureError("lambda.injectors contains duplicates")
        unknown = (set(lambda_.producers) | set(lambda_.injectors)) - set(wells)
        if unknown:
            raise FeatureError(f"lambda references unknown wells: {sorted(unknown)}")
        if len(lambda_.matrix) != len(lambda_.producers) or any(
            len(row) != len(lambda_.injectors) for row in lambda_.matrix
        ):
            raise FeatureError("the shape of lambda.matrix does not match the axes")
        if any(not math.isfinite(value) for row in lambda_.matrix for value in row):
            raise FeatureError("lambda.matrix contains a non-numeric value")


__all__ = [
    "ScheduleFeatureizer",
]
