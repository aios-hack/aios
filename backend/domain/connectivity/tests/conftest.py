from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.domain.connectivity import DeckSchedule, FundHistory, build_fund_history, parse_deck_schedule

DECK_ENV = "AIOS_DECK_SCHEDULE"
DEFAULT_DECK = Path(
    "W:/Projects/hacks/aios/docs/models/Model_Z/Model_Z_sch.inc"
)


def deck_path() -> Path:
    override = os.environ.get(DECK_ENV)
    return Path(override) if override else DEFAULT_DECK


@pytest.fixture(scope="session")
def deck() -> DeckSchedule:
    path = deck_path()
    if not path.exists():
        pytest.skip(f"дек не найден: {path}; путь задаётся через {DECK_ENV}")
    return parse_deck_schedule(path)


@pytest.fixture(scope="session")
def history(deck: DeckSchedule) -> FundHistory:
    return build_fund_history(deck)
