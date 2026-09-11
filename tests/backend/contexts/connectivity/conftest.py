from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.domain.connectivity import DeckSchedule, FundHistory, build_fund_history, parse_deck_schedule

from conftest import missing_reason, model_z_schedule

#: Явный путь к деку в обход поиска каталога docs. Нужен, когда дек лежит
#: не сиблингом репозитория; обычная раскладка разрешается сама.
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
        pytest.skip(missing_reason(f"дек Model_Z (либо путь через {DECK_ENV})"))
    return parse_deck_schedule(path)


@pytest.fixture(scope="session")
def history(deck: DeckSchedule) -> FundHistory:
    return build_fund_history(deck)
