from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.connectivity.domain.doe import Amplitude, DoEPlan, Level
from backend.contexts.connectivity.domain.errors import CampaignError
from backend.contexts.connectivity.domain.fund import ActiveFund, Window
from backend.contexts.reservoir.domain.response import N_DECK_DATES
from backend.contexts.schedule.domain.schedule import N_CONTROL_DATES

T0_DECK_DATE_INDEX = N_DECK_DATES - N_CONTROL_DATES

DEFAULT_WINDOW_STEPS = 24

DEFAULT_COVERAGE = 0.8

DEFAULT_BATCH_SEEDS = (20260820, 20260821, 20260822, 20260823)

BATCHES_PER_HALF = 2


@dataclass(frozen=True, slots=True)
class CampaignSetup:
    window: Window
    fund: ActiveFund
    amplitude: Amplitude
    plans: tuple[DoEPlan, ...]

    @property
    def n_runs(self) -> int:
        return sum(len(plan.rows) for plan in self.plans)


def level_factor(level: Level, amplitude: Amplitude) -> float:
    relative = amplitude.step_m3_per_day / amplitude.base_level_m3_per_day
    if level is Level.HIGH:
        return 1.0 + relative
    factor = 1.0 - relative
    if factor <= 0.0:
        raise CampaignError(
            f"the lower plan level zeroes the setpoint (factor {factor}): "
            "shutting a well in is not an amplitude perturbation"
        )
    return factor


__all__ = [
    "BATCHES_PER_HALF",
    "DEFAULT_BATCH_SEEDS",
    "DEFAULT_COVERAGE",
    "DEFAULT_WINDOW_STEPS",
    "T0_DECK_DATE_INDEX",
    "CampaignSetup",
    "level_factor",
]
