
from __future__ import annotations

from backend.contexts.surrogate.domain.errors import (
    AdapterError,
)

from datetime import date
from typing import Sequence

from backend.core.contracts import (
    IntervalResponse,
    N_CONTROL_DATES,
    N_INTERVALS,
    ResponseArtifact,
    Schedule,
    StateAtDate,
    hash_schedule,
)
from backend.contexts.simulation.infrastructure.response_loader import (
    _build_well_timelines,
    _fallback_control_mode,
)

from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput

from backend.contexts.reservoir.domain.horizon import HORIZON

_HISTORY_HORIZON = HORIZON.history_offset + 1


class ResponseAdapter:
    def adapt(
        self,
        raw: RawModelOutput,
        schedule: Schedule,
        historical: ResponseArtifact,
        control_dates: Sequence[date],
    ) -> tuple[tuple[StateAtDate, ...], tuple[IntervalResponse, ...]]:
        wells = tuple(schedule.meta.wells)
        if set(schedule.initial_state) != set(wells):
            raise AdapterError("Schedule.initial_state должен содержать ровно Schedule.meta.wells")
        if raw.wells != wells:
            raise AdapterError(
                "RawModelOutput.wells не совпадает с осью Schedule.meta.wells"
            )
        expected_hash = hash_schedule(schedule)
        if raw.canonical_schedule_hash != expected_hash:
            raise AdapterError(
                f"RawModelOutput предсказан не под этот Schedule: "
                f"{raw.canonical_schedule_hash!r} != {expected_hash!r}"
            )
        if len(control_dates) != N_CONTROL_DATES:
            raise AdapterError(
                f"control_dates должен содержать {N_CONTROL_DATES} дат, получено {len(control_dates)}"
            )
        if any(right <= left for left, right in zip(control_dates, control_dates[1:])):
            raise AdapterError("control_dates должны строго возрастать")
        interval_days = tuple(
            (control_dates[k + 1] - control_dates[k]).days for k in range(N_INTERVALS)
        )

        historical_by_key = {
            (state.deck_date_index, state.well): state for state in historical.state_at_date
        }
        for well in wells:
            for deck_date_index in range(_HISTORY_HORIZON):
                if (deck_date_index, well) not in historical_by_key:
                    raise AdapterError(
                        f"в базовом прогоне нет StateAtDate[{deck_date_index}, {well!r}] — "
                        "историческая часть неполна"
                    )

        timelines = _build_well_timelines(schedule)
        raw_by_key = {(node.well, node.control_step): node for node in raw.nodes}

        state_at_date: list[StateAtDate] = []
        interval_response: list[IntervalResponse] = []
        for well in wells:
            for deck_date_index in range(_HISTORY_HORIZON):
                state_at_date.append(historical_by_key[(deck_date_index, well)])

            last_historical = historical_by_key[(_HISTORY_HORIZON - 1, well)]
            timeline = timelines[well]
            for control_step in range(N_INTERVALS):
                node = raw_by_key[(well, control_step)]
                mode = _fallback_control_mode(
                    commissioned=timeline.is_commissioned(control_step),
                    operating_status=timeline.operating_status(control_step),
                    setpoint=timeline.setpoint(control_step),
                    liquid_rate=node.liquid_rate,
                    injection_rate=node.injection_rate,
                    bhp=node.bhp,
                )
                state_at_date.append(
                    StateAtDate(
                        deck_date_index=_HISTORY_HORIZON + control_step,
                        well=well,
                        liquid_rate=node.liquid_rate,
                        oil_rate=node.oil_mass_delta / interval_days[control_step],
                        injection_rate=node.injection_rate,
                        thp=last_historical.thp,
                        bhp=node.bhp,
                        well_efficiency=last_historical.well_efficiency,
                        active_control_mode=mode,
                    )
                )
                interval_response.append(
                    IntervalResponse(
                        control_step=control_step,
                        well=well,
                        oil_mass_delta=node.oil_mass_delta,
                        liquid_volume_delta=node.liquid_volume_delta,
                        injection_volume_delta=node.injection_volume_delta,
                    )
                )

        return tuple(state_at_date), tuple(interval_response)
