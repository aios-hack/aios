from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest

from backend.shared.clock import FrozenClock
from backend.shared.settings import Settings
from tests.support.backend.environment import (
    base_run_dir,
    base_run_output_dir,
    chdd_python_dir,
    docker_unavailable_reason,
    missing_reason,
    model_z_dir,
    model_z_schedule,
    normatives_xlsx,
    repo_root,
)
from tests.support.backend.paths import DECKS_ROOT, FIXTURES_ROOT, REPO_ROOT

FROZEN_MOMENT = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    return FIXTURES_ROOT


@pytest.fixture(scope="session")
def decks_root() -> Path:
    return DECKS_ROOT


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env({})


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {
            "AIOS_PROJECT_ROOT": str(tmp_path),
            "AIOS_DATA_ROOT": str(tmp_path / "data"),
            "AIOS_OUT_DIR": str(tmp_path / "out"),
        }
    )


@pytest.fixture
def tmp_out(tmp_path: Path) -> Iterator[Path]:
    target = tmp_path / "out"
    target.mkdir(parents=True, exist_ok=True)
    yield target


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(FROZEN_MOMENT)


@pytest.fixture(scope="session")
def model_z() -> Path:
    directory = model_z_dir()
    if directory is None:
        pytest.skip(missing_reason("the Model_Z directory"))
    return directory


@pytest.fixture(scope="session")
def model_z_deck() -> Path:
    deck = model_z_schedule()
    if deck is None:
        pytest.skip(missing_reason("the Model_Z_sch.inc deck"))
    return deck


@pytest.fixture(scope="session")
def normatives_workbook() -> Path:
    workbook = normatives_xlsx()
    if workbook is None:
        pytest.skip(missing_reason("Нормативы_ЧДД.xlsx"))
    return workbook


@pytest.fixture(scope="session")
def reference_calculator() -> Path:
    directory = chdd_python_dir()
    if directory is None:
        pytest.skip(missing_reason("the CHDD_PYTHON calculator"))
    return directory


@pytest.fixture(scope="session")
def base_run() -> Path:
    directory = base_run_dir()
    if directory is None:
        pytest.skip(missing_reason("the base OPM run"))
    return directory


@pytest.fixture(scope="session")
def base_run_output() -> Path:
    directory = base_run_output_dir()
    if directory is None:
        pytest.skip(missing_reason("the output of the base OPM run"))
    return directory


@pytest.fixture(scope="session")
def docker_ready() -> None:
    reason = docker_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
