from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.contexts.connectivity.infrastructure.deck import DeckSchedule, parse_deck_schedule
from backend.contexts.connectivity.domain.fund import FundHistory, build_fund_history

from tests.support.backend.environment import missing_reason, model_z_schedule

DECK_ENV = "AIOS_DECK_SCHEDULE"


def deck_path() -> Path | None:
    override = os.environ.get(DECK_ENV)
    if override:
        path = Path(override)
        return path if path.exists() else None
    return model_z_schedule()


@pytest.fixture(scope="session")
def deck() -> DeckSchedule:
    path = deck_path()
    if path is None:
        pytest.skip(missing_reason(f"Model_Z deck (or a path via {DECK_ENV})"))
    return parse_deck_schedule(path)


@pytest.fixture(scope="session")
def history(deck: DeckSchedule) -> FundHistory:
    return build_fund_history(deck)
