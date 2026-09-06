"""Apply outage and aggregate rate caps to a dense baseline control schedule.

Only control events are edited; history, commissioning and fixed deck events
are preserved. Outcome/volume constraints still require dynamic validation.
"""
from collections import defaultdict
from dataclasses import replace
from datetime import date
import math
from typing import Sequence
from backend.core.contracts import Constraints, EventKind, Schedule
from backend.domain.schedule.canonical import canonicalize


def apply_case_limits(schedule: Schedule, constraints: Constraints, dates: Sequence[date]) -> Schedule:
    if not (constraints.well_outages or constraints.injection_limits or constraints.liquid_limits):
        return schedule
    outages = {(outage.well, step) for outage in constraints.well_outages
               for step in range(outage.control_step_from, outage.control_step_to + 1)}
    events = []
    for event in schedule.control_events:
        if (event.well, event.control_step) in outages:
            if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
                event = replace(event, value=0.0)
            elif event.kind is EventKind.OPEN:
                event = replace(event, kind=EventKind.SHUT)
        events.append(event)
    totals = defaultdict(float)
    for event in events:
        if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
            totals[event.control_step, event.kind] += event.value or 0.0
    zeroed = set()
    for index, event in enumerate(events):
        caps = (constraints.injection_limits if event.kind is EventKind.SET_RATE
                else constraints.liquid_limits if event.kind is EventKind.SET_LRAT else {})
        cap = caps.get(dates[event.control_step].year)
        total = totals[event.control_step, event.kind]
        if cap is not None and total > cap and event.value:
            value = float(math.floor(event.value * cap / total))
            events[index] = replace(event, value=value)
            if value == 0:
                zeroed.add((event.well, event.control_step))
    events = [replace(event, kind=EventKind.SHUT)
              if event.kind is EventKind.OPEN and (event.well, event.control_step) in zeroed else event
              for event in events]
    return canonicalize(replace(schedule, control_events=tuple(events)))
