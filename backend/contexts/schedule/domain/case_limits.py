from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
import math
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, Sequence
from backend.core.contracts import Constraints, ControlEvent, EventKind, Schedule
from backend.contexts.schedule.domain.canonical import canonicalize

_EMPTY_YEARS: Mapping[int, float] = MappingProxyType({})

DEFAULT_ROUNDS = 8
_SAFETY = 0.98
_MIN_FACTOR_STEP = 0.999


class CaseLimitsError(RuntimeError):
    pass


class CaseLimitsForecastRequired(CaseLimitsError):
    pass


class CaseLimitsNotConverged(CaseLimitsError):
    pass


@dataclass(frozen=True, slots=True)
class YearlyProduction:
    liquid_by_year: Mapping[int, float] = field(default=_EMPTY_YEARS)
    injection_by_year: Mapping[int, float] = field(default=_EMPTY_YEARS)

    def by_kind(self, kind: EventKind) -> Mapping[int, float]:
        if kind is EventKind.SET_LRAT:
            return self.liquid_by_year
        if kind is EventKind.SET_RATE:
            return self.injection_by_year
        raise CaseLimitsError(f"годовой отбор не определён для события {kind.name}")


class ProductionForecast(Protocol):
    def __call__(self, schedule: Schedule) -> YearlyProduction: ...


ProductionForecastFn = Callable[[Schedule], YearlyProduction]


@dataclass(frozen=True, slots=True)
class CaseLimitsOutcome:
    schedule: Schedule
    forecast_used: bool
    rounds: int
    trimmed_years: Mapping[EventKind, tuple[int, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    setpoint_sum_fallback: bool = False


def _capped_kinds(constraints: Constraints) -> tuple[tuple[EventKind, Mapping[int, float]], ...]:
    return (
        (EventKind.SET_RATE, constraints.injection_limits),
        (EventKind.SET_LRAT, constraints.liquid_limits),
    )


def _apply_outages(schedule: Schedule, constraints: Constraints) -> tuple[ControlEvent, ...]:
    outages = {
        (outage.well, step)
        for outage in constraints.well_outages
        for step in range(outage.control_step_from, outage.control_step_to + 1)
    }
    events: list[ControlEvent] = []
    for event in schedule.control_events:
        if (event.well, event.control_step) in outages:
            if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
                event = replace(event, value=0.0)
            elif event.kind is EventKind.OPEN:
                event = replace(event, kind=EventKind.SHUT)
        events.append(event)
    return tuple(events)


def _year_of(dates: Sequence[date], control_step: int) -> int | None:
    if control_step >= len(dates):
        return None
    return dates[control_step].year


def _scale_events(
    events: Sequence[ControlEvent],
    dates: Sequence[date],
    factors: Mapping[tuple[EventKind, int], float],
) -> tuple[ControlEvent, ...]:
    zeroed: set[tuple[str, int]] = set()
    scaled: list[ControlEvent] = []
    for event in events:
        year = _year_of(dates, event.control_step)
        factor = factors.get((event.kind, year)) if year is not None else None
        if factor is not None and event.value:
            value = max(0.0, float(math.floor(float(event.value) * factor)))
            event = replace(event, value=value)
            if value == 0.0:
                zeroed.add((event.well, event.control_step))
        scaled.append(event)
    return tuple(
        replace(event, kind=EventKind.SHUT)
        if event.kind is EventKind.OPEN and (event.well, event.control_step) in zeroed
        else event
        for event in scaled
    )


def _setpoint_sums(
    events: Sequence[ControlEvent], dates: Sequence[date], kind: EventKind
) -> dict[int, float]:
    sums: dict[int, float] = {}
    for event in events:
        if event.kind is not kind:
            continue
        year = _year_of(dates, event.control_step)
        if year is None:
            continue
        sums[year] = sums.get(year, 0.0) + float(event.value or 0.0)
    return sums


def _excess_factors(
    actual: Mapping[int, float], caps: Mapping[int, float]
) -> dict[int, float]:
    factors: dict[int, float] = {}
    for year, cap in caps.items():
        produced = actual.get(year)
        if produced is None:
            raise CaseLimitsForecastRequired(
                f"прогноз годового отбора не содержит {year}: лимит проверить нечем"
            )
        if produced <= cap:
            continue
        if produced <= 0.0:
            raise CaseLimitsError(
                f"{year}: превышение лимита при неположительном отборе {produced}"
            )
        factors[year] = min(_MIN_FACTOR_STEP, _SAFETY * cap / produced)
    return factors


def _trim_by_forecast(
    schedule: Schedule,
    constraints: Constraints,
    dates: Sequence[date],
    forecast: ProductionForecastFn,
    rounds: int,
) -> CaseLimitsOutcome:
    current = schedule
    trimmed: dict[EventKind, set[int]] = {}
    for round_index in range(rounds + 1):
        actual = forecast(current)
        factors: dict[tuple[EventKind, int], float] = {}
        for kind, caps in _capped_kinds(constraints):
            if not caps:
                continue
            for year, factor in _excess_factors(actual.by_kind(kind), caps).items():
                factors[(kind, year)] = factor
        if not factors:
            return CaseLimitsOutcome(
                schedule=current,
                forecast_used=True,
                rounds=round_index,
                trimmed_years=MappingProxyType(
                    {kind: tuple(sorted(years)) for kind, years in trimmed.items()}
                ),
            )
        if round_index == rounds:
            raise CaseLimitsNotConverged(
                f"годовые лимиты не выполнены за {rounds} итераций: "
                f"остались превышения {sorted((kind.name, year) for kind, year in factors)}"
            )
        for kind, year in factors:
            trimmed.setdefault(kind, set()).add(year)
        current = canonicalize(
            replace(current, control_events=_scale_events(current.control_events, dates, factors))
        )
    raise CaseLimitsNotConverged("недостижимо")


def _trim_by_setpoint_sum(
    schedule: Schedule, constraints: Constraints, dates: Sequence[date]
) -> CaseLimitsOutcome:
    events = tuple(schedule.control_events)
    factors: dict[tuple[EventKind, int], float] = {}
    trimmed: dict[EventKind, set[int]] = {}
    for kind, caps in _capped_kinds(constraints):
        if not caps:
            continue
        sums = _setpoint_sums(events, dates, kind)
        for year, cap in caps.items():
            total = sums.get(year, 0.0)
            if total > cap and total > 0.0:
                factors[(kind, year)] = cap / total
                trimmed.setdefault(kind, set()).add(year)
    if not factors:
        return CaseLimitsOutcome(
            schedule=canonicalize(replace(schedule, control_events=events)),
            forecast_used=False,
            rounds=0,
            setpoint_sum_fallback=True,
        )
    return CaseLimitsOutcome(
        schedule=canonicalize(
            replace(schedule, control_events=_scale_events(events, dates, factors))
        ),
        forecast_used=False,
        rounds=1,
        trimmed_years=MappingProxyType(
            {kind: tuple(sorted(years)) for kind, years in trimmed.items()}
        ),
        setpoint_sum_fallback=True,
    )


def apply_case_limits_report(
    schedule: Schedule,
    constraints: Constraints,
    dates: Sequence[date],
    forecast: ProductionForecastFn | None = None,
    *,
    allow_setpoint_sum_fallback: bool = False,
    rounds: int = DEFAULT_ROUNDS,
) -> CaseLimitsOutcome:
    if rounds < 0:
        raise CaseLimitsError(f"rounds={rounds}: число итераций не может быть отрицательным")
    has_caps = bool(constraints.injection_limits or constraints.liquid_limits)
    if not (constraints.well_outages or has_caps):
        return CaseLimitsOutcome(schedule=schedule, forecast_used=False, rounds=0)
    with_outages = canonicalize(
        replace(schedule, control_events=_apply_outages(schedule, constraints))
    )
    if not has_caps:
        return CaseLimitsOutcome(schedule=with_outages, forecast_used=False, rounds=0)
    if forecast is None:
        if not allow_setpoint_sum_fallback:
            raise CaseLimitsForecastRequired(
                "годовые лимиты заданы, но прогноз фактического отбора не передан: "
                "резка по сумме целевых уставок урезает план, который лимит не нарушает. "
                "Передайте forecast или явно включите allow_setpoint_sum_fallback=True"
            )
        return _trim_by_setpoint_sum(with_outages, constraints, dates)
    return _trim_by_forecast(with_outages, constraints, dates, forecast, rounds)


def apply_case_limits(
    schedule: Schedule,
    constraints: Constraints,
    dates: Sequence[date],
    forecast: ProductionForecastFn | None = None,
    *,
    allow_setpoint_sum_fallback: bool = False,
    rounds: int = DEFAULT_ROUNDS,
) -> Schedule:
    return apply_case_limits_report(
        schedule,
        constraints,
        dates,
        forecast,
        allow_setpoint_sum_fallback=allow_setpoint_sum_fallback,
        rounds=rounds,
    ).schedule
