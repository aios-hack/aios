
from __future__ import annotations

from backend.contexts.connectivity.domain.errors import (
    CampaignError,
)

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.core.contracts import N_CONTROL_DATES, Role, Schedule
from backend.contexts.reservoir.domain.response import N_DECK_DATES
from backend.shared.paths import data_root
from backend.contexts.connectivity.infrastructure.deck import parse_deck_schedule
from backend.contexts.connectivity.domain.doe import (
    Amplitude,
    DoEPlan,
    Level,
    amplitude_from_prior,
    plackett_burman,
)
from backend.contexts.connectivity.domain.fund import (
    ActiveFund,
    Window,
    active_fund_in_window,
    build_fund_history,
)
from backend.contexts.connectivity.domain.setpoints import setpoint_changes

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


def setup(
    model_dir: Path | str,
    base: Schedule,
    *,
    n_steps: int = DEFAULT_WINDOW_STEPS,
    coverage: float = DEFAULT_COVERAGE,
    batch_seeds: Sequence[int] = DEFAULT_BATCH_SEEDS,
) -> CampaignSetup:
    if len(batch_seeds) < 2 * BATCHES_PER_HALF:
        raise CampaignError(
            f"партий {len(batch_seeds)}: устойчивость λ меряется двумя "
            f"независимыми половинами по {BATCHES_PER_HALF} партии (§8.2), "
            f"а одна партия на {len(batch_seeds)} сидах недоопределена — "
            f"строк плана меньше, чем параметров регрессии"
        )
    deck = parse_deck_schedule(Path(model_dir) / "Model_Z_sch.inc")
    start = deck.dates[T0_DECK_DATE_INDEX]
    end = deck.dates[T0_DECK_DATE_INDEX + n_steps]
    window = Window(start=start, end=end)

    history = build_fund_history(deck)
    fund = active_fund_in_window(deck, window, history)
    if not fund.injectors:
        raise CampaignError(f"в окне {start}…{end} нет активных нагнетательных")

    distribution = setpoint_changes(deck, Role.INJ, T0_DECK_DATE_INDEX)
    amplitude = amplitude_from_prior(distribution, coverage)

    plans = tuple(
        plackett_burman(window, fund, amplitude, seed) for seed in batch_seeds
    )
    return CampaignSetup(window=window, fund=fund, amplitude=amplitude, plans=plans)


def level_factor(level: Level, amplitude: Amplitude) -> float:
    relative = amplitude.step_m3_per_day / amplitude.base_level_m3_per_day
    if level is Level.HIGH:
        return 1.0 + relative
    factor = 1.0 - relative
    if factor <= 0.0:
        raise CampaignError(
            f"нижний уровень плана обнуляет уставку (множитель {factor}): "
            "остановка скважины — не возмущение амплитуды"
        )
    return factor
