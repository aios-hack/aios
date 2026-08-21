"""Model output adapter — task 33.

Turns a :class:`~surrogate.raw_model_output.RawModelOutput` prediction plus
the real base-run response into the two canonical types every downstream
consumer (``Economics``, ``ProductionLedger``, ``EspStateMachine``) expects:
``StateAtDate`` (371 dates) and ``IntervalResponse`` (224 intervals), "той же
формы, что выдаёт ``ResponseLoader``" (docs/context/08_contracts.md §5.1).

Historical part of ``StateAtDate`` (deck_date_index 0…146) is spliced in
verbatim from the base run, never from the model (§5.1's axis table). The
predicted part (147…370 / control_step 0…223) comes from ``raw``, with two
derived fields the model never emits directly:

- ``oil_rate`` — §5.1.1 forbids predicting oil rate as a channel (the
  achievability trap); derived as ``oil_mass_delta / interval_days``.
- ``active_control_mode`` — diagnostic-only (§4.1.1); there is no ``WMCTL``
  analogue for a neural model, so this always goes through the same
  fact/target fallback rule ``bridge.response_loader`` uses when OPM's
  ``WMCTL`` itself is unavailable — imported directly rather than
  reimplemented, to avoid a second copy of its threshold constants drifting
  out of sync.

``thp``/``well_efficiency`` have no consumer anywhere in the pipeline today
(``Economics``/``ProductionLedger``/``EspStateMachine`` read only
``liquid_rate``/``injection_rate``/``bhp``) — held forward from the last
historical value (deck_date_index 146) rather than modeled.

Returns bare tuples, not a ``contracts.ResponseArtifact``: that type's
``source_run_id`` documents a real OPM run (§6a), and wrapping a surrogate
prediction in it would create exactly the kind of surrogate-as-source-of-NPV
risk task 62 exists to rule out.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from aios_backend.core.contracts import (
    IntervalResponse,
    N_CONTROL_DATES,
    N_INTERVALS,
    ResponseArtifact,
    Schedule,
    StateAtDate,
    hash_schedule,
)
from aios_backend.infrastructure.opm.response_loader import _build_well_timelines, _fallback_control_mode

from .raw_model_output import RawModelOutput

_HISTORY_HORIZON = 147  # deck_date_index 0…146 — историческая часть StateAtDate


class AdapterError(ValueError):
    """RawModelOutput/Schedule/базовый прогон нельзя склеить в валидный отклик."""


class ResponseAdapter:
    """RawModelOutput + Schedule + базовый ResponseArtifact → StateAtDate + IntervalResponse."""

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
