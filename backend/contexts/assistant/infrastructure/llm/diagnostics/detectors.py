from __future__ import annotations

from typing import Mapping, Sequence

from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate
from backend.contexts.schedule.domain.schedule import Role, Schedule
from backend.contexts.assistant.infrastructure.llm.diagnostics.model import (
    PATTERNS,
    Finding,
    Thresholds,
    sorted_steps,
    steps_by_well,
    wells_with_role,
)


def detect_injection_response_lag(
    interval_response: Sequence[IntervalResponse],
    schedule: Schedule,
    injection_delta_min: float,
    lag_oil_delta_min: float,
    max_lag_steps: int,
) -> list[Finding]:
    by_well = steps_by_well(interval_response)
    producers = wells_with_role(schedule, Role.PROD)
    field_oil: dict[int, float] = {}
    for well in producers:
        for step, row in by_well.get(well, {}).items():
            field_oil[step] = field_oil.get(step, 0.0) + row.oil_mass_delta
    findings: list[Finding] = []
    for injector in wells_with_role(schedule, Role.INJ):
        rows = by_well.get(injector, {})
        steps = sorted_steps(rows)
        for prev, curr in zip(steps, steps[1:]):
            injection_delta = (
                rows[curr].injection_volume_delta - rows[prev].injection_volume_delta
            )
            if abs(injection_delta) < injection_delta_min:
                continue
            for lag in range(1, max_lag_steps + 1):
                at = curr + lag
                if at not in field_oil or at - 1 not in field_oil:
                    break
                oil_delta = field_oil[at] - field_oil[at - 1]
                if abs(oil_delta) >= lag_oil_delta_min:
                    findings.append(
                        Finding(
                            pattern_id="injection_response_lag",
                            name_ru=PATTERNS["injection_response_lag"],
                            well=injector,
                            severity="info",
                            inputs={
                                "injection_delta": injection_delta,
                                "oil_delta": oil_delta,
                                "lag_steps": float(lag),
                            },
                            control_step=curr,
                        )
                    )
                    break
    return findings


def detect_wct_rise_without_oil(
    interval_response: Sequence[IntervalResponse],
    schedule: Schedule,
    watercut: Mapping[tuple[int, str], float],
    wct_delta_min: float,
    oil_delta_max: float,
) -> list[Finding]:
    by_well = steps_by_well(interval_response)
    findings: list[Finding] = []
    for well in wells_with_role(schedule, Role.PROD):
        rows = by_well.get(well, {})
        steps = sorted_steps(rows)
        for prev, curr in zip(steps, steps[1:]):
            if (prev, well) not in watercut or (curr, well) not in watercut:
                continue
            wct_prev = watercut[(prev, well)]
            wct_curr = watercut[(curr, well)]
            oil_delta = rows[curr].oil_mass_delta - rows[prev].oil_mass_delta
            if wct_curr - wct_prev >= wct_delta_min and oil_delta <= oil_delta_max:
                findings.append(
                    Finding(
                        pattern_id="wct_rise_without_oil",
                        name_ru=PATTERNS["wct_rise_without_oil"],
                        well=well,
                        severity="warning",
                        inputs={
                            "watercut_prev": wct_prev,
                            "watercut_curr": wct_curr,
                            "oil_delta": oil_delta,
                        },
                        control_step=curr,
                    )
                )
    return findings


def detect_liquid_jump_flat_oil(
    interval_response: Sequence[IntervalResponse],
    schedule: Schedule,
    watercut: Mapping[tuple[int, str], float],
    liquid_delta_min: float,
    oil_delta_abs_max: float,
    wct_delta_min: float,
) -> list[Finding]:
    by_well = steps_by_well(interval_response)
    findings: list[Finding] = []
    for well in wells_with_role(schedule, Role.PROD):
        rows = by_well.get(well, {})
        steps = sorted_steps(rows)
        for prev, curr in zip(steps, steps[1:]):
            if (prev, well) not in watercut or (curr, well) not in watercut:
                continue
            liquid_delta = (
                rows[curr].liquid_volume_delta - rows[prev].liquid_volume_delta
            )
            oil_delta = rows[curr].oil_mass_delta - rows[prev].oil_mass_delta
            wct_prev = watercut[(prev, well)]
            wct_curr = watercut[(curr, well)]
            if (
                liquid_delta >= liquid_delta_min
                and abs(oil_delta) <= oil_delta_abs_max
                and wct_curr - wct_prev >= wct_delta_min
            ):
                findings.append(
                    Finding(
                        pattern_id="liquid_jump_flat_oil",
                        name_ru=PATTERNS["liquid_jump_flat_oil"],
                        well=well,
                        severity="warning",
                        inputs={
                            "liquid_delta": liquid_delta,
                            "oil_delta": oil_delta,
                            "watercut_prev": wct_prev,
                            "watercut_curr": wct_curr,
                        },
                        control_step=curr,
                    )
                )
    return findings


def detect_pressure_drop_at_high_rates(
    state_at_date: Sequence[StateAtDate],
    bhp_drop_min: float,
    liquid_rate_min: float,
) -> list[Finding]:
    by_well: dict[str, dict[int, StateAtDate]] = {}
    for row in state_at_date:
        by_well.setdefault(row.well, {})[row.deck_date_index] = row
    findings: list[Finding] = []
    for well in sorted(by_well):
        rows = by_well[well]
        dates = sorted(rows)
        for prev, curr in zip(dates, dates[1:]):
            bhp_prev = rows[prev].bhp
            bhp_curr = rows[curr].bhp
            liquid_rate = rows[curr].liquid_rate
            if (
                liquid_rate >= liquid_rate_min
                and rows[prev].liquid_rate >= liquid_rate_min
                and bhp_prev - bhp_curr >= bhp_drop_min
            ):
                findings.append(
                    Finding(
                        pattern_id="pressure_drop_at_high_rates",
                        name_ru=PATTERNS["pressure_drop_at_high_rates"],
                        well=well,
                        severity="warning",
                        inputs={
                            "bhp_prev": bhp_prev,
                            "bhp_curr": bhp_curr,
                            "liquid_rate": liquid_rate,
                        },
                        window=(prev, curr),
                    )
                )
    return findings


def detect_injection_without_response(
    interval_response: Sequence[IntervalResponse],
    schedule: Schedule,
    injection_volume_min: float,
    oil_delta_max: float,
    window_steps: int,
) -> list[Finding]:
    by_well = steps_by_well(interval_response)
    producers = wells_with_role(schedule, Role.PROD)
    field_oil: dict[int, float] = {}
    for well in producers:
        for step, row in by_well.get(well, {}).items():
            field_oil[step] = field_oil.get(step, 0.0) + row.oil_mass_delta
    findings: list[Finding] = []
    for injector in wells_with_role(schedule, Role.INJ):
        rows = by_well.get(injector, {})
        steps = sorted_steps(rows)
        for start_index in range(0, len(steps) - window_steps + 1):
            window = steps[start_index : start_index + window_steps]
            if window[-1] - window[0] != window_steps - 1:
                continue
            if any(step not in field_oil for step in window):
                continue
            injection_total = sum(
                rows[step].injection_volume_delta for step in window
            )
            oil_delta = field_oil[window[-1]] - field_oil[window[0]]
            if injection_total >= injection_volume_min and oil_delta <= oil_delta_max:
                findings.append(
                    Finding(
                        pattern_id="injection_without_response",
                        name_ru=PATTERNS["injection_without_response"],
                        well=injector,
                        severity="warning",
                        inputs={
                            "injection_total": injection_total,
                            "oil_delta": oil_delta,
                        },
                        window=(window[0], window[-1]),
                    )
                )
    return findings


def detect_oil_rise_without_liquid(
    interval_response: Sequence[IntervalResponse],
    schedule: Schedule,
    oil_delta_min: float,
    liquid_delta_max: float,
) -> list[Finding]:
    by_well = steps_by_well(interval_response)
    findings: list[Finding] = []
    for well in wells_with_role(schedule, Role.PROD):
        rows = by_well.get(well, {})
        steps = sorted_steps(rows)
        for prev, curr in zip(steps, steps[1:]):
            oil_delta = rows[curr].oil_mass_delta - rows[prev].oil_mass_delta
            liquid_delta = (
                rows[curr].liquid_volume_delta - rows[prev].liquid_volume_delta
            )
            if oil_delta >= oil_delta_min and liquid_delta <= liquid_delta_max:
                findings.append(
                    Finding(
                        pattern_id="oil_rise_without_liquid",
                        name_ru=PATTERNS["oil_rise_without_liquid"],
                        well=well,
                        severity="info",
                        inputs={
                            "oil_delta": oil_delta,
                            "liquid_delta": liquid_delta,
                        },
                        control_step=curr,
                    )
                )
    return findings


def detect_all(
    state_at_date: Sequence[StateAtDate],
    interval_response: Sequence[IntervalResponse],
    schedule: Schedule,
    watercut: Mapping[tuple[int, str], float],
    thresholds: Thresholds,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(
        detect_injection_response_lag(
            interval_response,
            schedule,
            thresholds.injection_delta_min,
            thresholds.lag_oil_delta_min,
            thresholds.max_lag_steps,
        )
    )
    findings.extend(
        detect_wct_rise_without_oil(
            interval_response,
            schedule,
            watercut,
            thresholds.wct_delta_min,
            thresholds.oil_delta_max,
        )
    )
    findings.extend(
        detect_liquid_jump_flat_oil(
            interval_response,
            schedule,
            watercut,
            thresholds.liquid_delta_min,
            thresholds.oil_delta_abs_max,
            thresholds.wct_delta_min,
        )
    )
    findings.extend(
        detect_pressure_drop_at_high_rates(
            state_at_date,
            thresholds.bhp_drop_min,
            thresholds.liquid_rate_min,
        )
    )
    findings.extend(
        detect_injection_without_response(
            interval_response,
            schedule,
            thresholds.injection_volume_min,
            thresholds.oil_delta_max,
            thresholds.window_steps,
        )
    )
    findings.extend(
        detect_oil_rise_without_liquid(
            interval_response,
            schedule,
            thresholds.oil_delta_min,
            thresholds.liquid_delta_max,
        )
    )
    return findings
