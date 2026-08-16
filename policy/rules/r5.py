from __future__ import annotations

from contracts import ControlEvent, EventKind, Role, Rule, Theta, TraceEntry

from policy.rules.base import RuleOutcome
from policy.state import PolicyState, RuleContext
from policy.theta import read

RULE = Rule.R5
ADMISSION_CRITERION = "Держим компенсацию участка в коридоре."
THETA_NAMES: tuple[str, ...] = ("r5_compensation_low", "r5_compensation_high")


def compensation(injection_m3_per_day: float, offtake_m3_per_day: float) -> float:
    if offtake_m3_per_day <= 0.0:
        raise ValueError(
            "компенсация не определена при нулевом отборе участка"
        )
    return injection_m3_per_day / offtake_m3_per_day


def corrected_group_injection(
    injection_m3_per_day: float,
    offtake_m3_per_day: float,
    low: float,
    high: float,
) -> float:
    current = compensation(injection_m3_per_day, offtake_m3_per_day)
    if current < low:
        return offtake_m3_per_day * low
    if current > high:
        return offtake_m3_per_day * high
    return injection_m3_per_day


def _group_of(context: RuleContext, well: str) -> str | None:
    if context.groups is None:
        return None
    for group_id, wells in context.groups.groups.items():
        if well in wells:
            return group_id
    return None


def apply(state: PolicyState, context: RuleContext, theta: Theta) -> RuleOutcome:
    low = read(theta, "r5_compensation_low")
    high = read(theta, "r5_compensation_high")
    if low > high:
        raise ValueError(
            f"коридор компенсации пуст: нижняя граница {low} выше верхней {high}"
        )
    if context.groups is None:
        raise ValueError(
            "R5 требует нарезку на участки: компенсация — величина участка, "
            "а не отдельной скважины"
        )
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    for group_id in sorted(context.groups.groups):
        injection = context.group_injection_m3_per_day.get(group_id)
        offtake = context.group_offtake_m3_per_day.get(group_id)
        if injection is None or offtake is None:
            raise ValueError(
                f"участок {group_id}: нет закачки или отбора, коридор "
                f"компенсации не проверяется"
            )
        if offtake <= 0.0:
            continue
        current = compensation(injection, offtake)
        target_total = corrected_group_injection(injection, offtake, low, high)
        if target_total == injection:
            continue
        injectors = tuple(
            well
            for well in sorted(context.groups.groups[group_id])
            if well in state.wells
            and state.wells[well].role is Role.INJ
            and state.wells[well].is_open
        )
        if not injectors:
            continue
        current_total = sum(
            state.wells[well].injection_rate_m3_per_day for well in injectors
        )
        for well in injectors:
            observation = state.wells[well]
            if current_total > 0.0:
                share = observation.injection_rate_m3_per_day / current_total
            else:
                share = 1.0 / len(injectors)
            target = target_total * share
            decisions.append(
                ControlEvent(
                    control_step=state.control_step,
                    well=well,
                    kind=EventKind.SET_RATE,
                    value=target,
                )
            )
            trace.append(
                TraceEntry(
                    control_step=state.control_step,
                    well=well,
                    rule=RULE,
                    inputs={
                        "group_injection_m3_per_day": injection,
                        "group_offtake_m3_per_day": offtake,
                        "compensation": current,
                        "theta_r5_compensation_low": low,
                        "theta_r5_compensation_high": high,
                        "target_group_injection_m3_per_day": target_total,
                        "target_compensation": target_total / offtake,
                        "share_of_group": share,
                        "previous_setpoint_m3_per_day": (
                            observation.setpoint_m3_per_day
                        ),
                        "target_rate_m3_per_day": target,
                    },
                    decision="SET_RATE",
                )
            )
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
