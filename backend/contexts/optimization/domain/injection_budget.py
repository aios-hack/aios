from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    ScheduleSearchError,
)
import math
from dataclasses import dataclass, replace
from typing import (
    Callable,
    Sequence,
)
from backend.core.contracts import (
    Constraints,
    ControlEvent,
    EventKind,
    Schedule,
    water_supply_policy,
)
from backend.contexts.policy.domain.budget import (
    interval_produced_water_rate_m3_per_day,
)
from backend.contexts.policy.domain.agents.projection import (
    HardConstraints,
    project_to_hard_constraints,
)
from backend.contexts.schedule.domain.canonical import canonicalize


Projection = Callable[[ControlEvent, HardConstraints], ControlEvent]


UNCONSTRAINED_WELLS = HardConstraints(well_cap_m3_per_day={})


_UNCONSTRAINED_FIELD_LIMIT_M3_PER_DAY = 1.0e7


PHYSICAL_HEADROOM = 1.2


SETPOINT_STEP_M3_PER_DAY = 1.0


WATER_COMMAND_SAFETY_FACTOR = 0.95


_interval_produced_water_rate_m3_per_day = interval_produced_water_rate_m3_per_day


SOURCE_PHYSICAL_HEADROOM = "physical_headroom"


SOURCE_CASE_INJECTION_LIMIT = "case_injection_limit"


SOURCE_WATER_BALANCE = "water_balance"


SOURCE_COMMAND_MARGIN = "command_margin"


SOURCE_WATER_BALANCE_REPAIR = "water_balance_repair"


UNCONSTRAINED_BUDGET_M3_PER_DAY = float("inf")


@dataclass(frozen=True, slots=True)
class InjectionBudget:

    control_step: int
    limit_m3_per_day: float
    binding_source: str
    contributions: tuple[tuple[str, float], ...]

    @property
    def unconstrained(self) -> bool:
        return not math.isfinite(self.limit_m3_per_day)

    def as_trace_entry(self) -> dict[str, object]:
        return {
            "control_step": self.control_step,
            "limit_m3_per_day": self.limit_m3_per_day,
            "binding_source": self.binding_source,
            "contributions": {name: value for name, value in self.contributions},
        }


def injection_budget_for_step(
    *,
    control_step: int,
    constraints: Constraints,
    year: int,
    produced_water_by_step: Sequence[float],
    physical_limit_m3_per_day: float | None = None,
    command_margin: float = 1.0,
) -> InjectionBudget:

    if not 0.0 < command_margin <= 1.0:
        raise ScheduleSearchError(
            f"control_step={control_step}: запас команды закачки должен лежать "
            f"в диапазоне (0, 1], получено {command_margin}"
        )
    contributions: list[tuple[str, float]] = []
    if physical_limit_m3_per_day is not None:
        contributions.append(
            (SOURCE_PHYSICAL_HEADROOM, float(physical_limit_m3_per_day))
        )
    explicit = constraints.injection_limits.get(year)
    if explicit is not None:
        contributions.append((SOURCE_CASE_INJECTION_LIMIT, float(explicit)))

    water = water_supply_policy(constraints)
    if water.enabled:
        source_step = control_step - water.lag_steps
        produced = (
            produced_water_by_step[source_step]
            if 0 <= source_step < len(produced_water_by_step)
            else 0.0
        )
        water_limit = water.limit(produced)
        if water_limit is None:
            raise ScheduleSearchError(
                f"control_step={control_step}: политика воды включена, но "
                "потолок закачки по водному балансу не посчитан"
            )
        contributions.append((SOURCE_WATER_BALANCE, float(water_limit)))

    if not contributions:
        return InjectionBudget(
            control_step=control_step,
            limit_m3_per_day=UNCONSTRAINED_BUDGET_M3_PER_DAY,
            binding_source="none",
            contributions=(),
        )

    binding_source, raw_limit = min(contributions, key=lambda item: item[1])
    limit = max(0.0, raw_limit)
    if command_margin < 1.0:
        limit *= command_margin
        contributions.append((SOURCE_COMMAND_MARGIN, limit))
        binding_source = SOURCE_COMMAND_MARGIN
    return InjectionBudget(
        control_step=control_step,
        limit_m3_per_day=limit,
        binding_source=binding_source,
        contributions=tuple(contributions),
    )


def _field_limit_for_step(
    *,
    physical_limit_m3_per_day: float,
    constraints: Constraints,
    year: int,
    control_step: int,
    produced_water_by_step: Sequence[float],
) -> float:

    return injection_budget_for_step(
        control_step=control_step,
        constraints=constraints,
        year=year,
        produced_water_by_step=produced_water_by_step,
        physical_limit_m3_per_day=physical_limit_m3_per_day,
    ).limit_m3_per_day


def _scale_step_injection_to_limit(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    limit_m3_per_day: float,
    *,
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    hard: HardConstraints = UNCONSTRAINED_WELLS,
    projection: Projection = project_to_hard_constraints,
) -> float:

    keys = [
        key
        for key in pending
        if key[0] == step and key[2] is EventKind.SET_RATE
    ]
    total = sum(float(pending[key].value or 0.0) for key in keys)
    if not math.isfinite(limit_m3_per_day) or total <= limit_m3_per_day + 1.0e-9:
        return total
    factor = 0.0 if total <= 0.0 else limit_m3_per_day / total
    for key in keys:
        event = pending[key]
        raw_value = float(event.value or 0.0) * factor
        value = (
            math.floor(raw_value / SETPOINT_STEP_M3_PER_DAY)
            * SETPOINT_STEP_M3_PER_DAY
        )
        admit_candidate(pending, replace(event, value=value), hard, projection)
        current_setpoint[event.well] = value
        if value <= 0.0:
            current_is_open[event.well] = False
            pending.pop((step, event.well, EventKind.OPEN), None)
            admit_candidate(
                pending,
                ControlEvent(
                    control_step=step,
                    well=event.well,
                    kind=EventKind.SHUT,
                ),
                hard,
                projection,
            )
    return sum(float(pending[key].value or 0.0) for key in keys)


DAMPER_STEP_FRACTION = 0.5


def _damped_value(prior: float, proposed: float) -> float:
    blended = prior + (proposed - prior) * DAMPER_STEP_FRACTION
    return math.floor(blended / SETPOINT_STEP_M3_PER_DAY) * SETPOINT_STEP_M3_PER_DAY


def _relax_rate_layer(
    previous: Schedule, proposed: Schedule, *, symmetric: bool = True
) -> Schedule:

    rate_kinds = (EventKind.SET_LRAT, EventKind.SET_RATE)
    previous_rates = {
        (event.control_step, event.well, event.kind): float(event.value or 0.0)
        for event in previous.control_events
        if event.kind in rate_kinds
    }
    relaxed_rates: dict[tuple[int, str], float] = {}
    events: list[ControlEvent] = []
    for event in proposed.control_events:
        if event.kind not in rate_kinds:
            events.append(event)
            continue
        value = float(event.value or 0.0)
        prior = previous_rates.get((event.control_step, event.well, event.kind))
        if prior is not None and value > 0.0:
            if event.kind is EventKind.SET_RATE and not symmetric:
                value = min(value, prior)
            else:
                value = _damped_value(prior, value)
        value = max(0.0, value)
        events.append(replace(event, value=value))
        relaxed_rates[(event.control_step, event.well)] = value

    normalized: list[ControlEvent] = []
    for event in events:
        if event.kind in (EventKind.OPEN, EventKind.SHUT):
            value = relaxed_rates.get((event.control_step, event.well))
            if value is not None:
                event = replace(
                    event,
                    kind=EventKind.OPEN if value > 0.0 else EventKind.SHUT,
                )
        normalized.append(event)
    return canonicalize(replace(proposed, control_events=tuple(normalized)))


def admit_candidate(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    event: ControlEvent,
    hard: HardConstraints,
    projection: Projection = project_to_hard_constraints,
) -> ControlEvent:

    admitted = projection(event, hard)
    pending[(admitted.control_step, admitted.well, admitted.kind)] = admitted
    return admitted


__all__ = [
    "admit_candidate",
    "DAMPER_STEP_FRACTION",
    "InjectionBudget",
    "PHYSICAL_HEADROOM",
    "Projection",
    "SETPOINT_STEP_M3_PER_DAY",
    "SOURCE_CASE_INJECTION_LIMIT",
    "SOURCE_COMMAND_MARGIN",
    "SOURCE_PHYSICAL_HEADROOM",
    "SOURCE_WATER_BALANCE",
    "SOURCE_WATER_BALANCE_REPAIR",
    "UNCONSTRAINED_BUDGET_M3_PER_DAY",
    "UNCONSTRAINED_WELLS",
    "WATER_COMMAND_SAFETY_FACTOR",
    "injection_budget_for_step",
]
