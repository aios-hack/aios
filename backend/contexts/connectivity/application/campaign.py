
from __future__ import annotations

from backend.contexts.connectivity.domain.errors import (
    CampaignError,
)

from pathlib import Path
from typing import Sequence

from backend.contexts.schedule.domain.schedule import Role, Schedule
from backend.contexts.connectivity.domain.campaign_plan import (
    BATCHES_PER_HALF,
    CampaignSetup,
    DEFAULT_BATCH_SEEDS,
    DEFAULT_COVERAGE,
    DEFAULT_WINDOW_STEPS,
    T0_DECK_DATE_INDEX,
    level_factor,
)
from backend.contexts.connectivity.infrastructure.deck import parse_deck_schedule
from backend.contexts.connectivity.domain.doe import (
    amplitude_from_prior,
    plackett_burman,
)
from backend.contexts.connectivity.domain.fund import (
    Window,
    active_fund_in_window,
    build_fund_history,
)
from backend.contexts.connectivity.domain.setpoints import setpoint_changes

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
            f"{len(batch_seeds)} batches: lambda stability is measured by two "
            f"independent halves of {BATCHES_PER_HALF} batches each (section 8.2), "
            f"and one batch over {len(batch_seeds)} seeds is underdetermined — "
            f"the plan has fewer rows than the regression has parameters"
        )
    deck = parse_deck_schedule(Path(model_dir) / "Model_Z_sch.inc")
    start = deck.dates[T0_DECK_DATE_INDEX]
    end = deck.dates[T0_DECK_DATE_INDEX + n_steps]
    window = Window(start=start, end=end)

    history = build_fund_history(deck)
    fund = active_fund_in_window(deck, window, history)
    if not fund.injectors:
        raise CampaignError(f"no active injectors in the window {start}…{end}")

    distribution = setpoint_changes(deck, Role.INJ, T0_DECK_DATE_INDEX)
    amplitude = amplitude_from_prior(distribution, coverage)

    plans = tuple(
        plackett_burman(window, fund, amplitude, seed) for seed in batch_seeds
    )
    return CampaignSetup(window=window, fund=fund, amplitude=amplitude, plans=plans)


__all__ = [
    "BATCHES_PER_HALF",
    "CampaignError",
    "CampaignSetup",
    "DEFAULT_BATCH_SEEDS",
    "DEFAULT_COVERAGE",
    "DEFAULT_WINDOW_STEPS",
    "T0_DECK_DATE_INDEX",
    "level_factor",
    "setup",
]
