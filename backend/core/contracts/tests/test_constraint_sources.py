from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.application.cases import (
    CaseError,
    INFRASTRUCTURE_KEYS,
    constraints_from_json,
    load_case,
)
from backend.core.contracts.constraints import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
    BLOCKING_INFRASTRUCTURE_KEYS,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    EXTERNAL_WATER_M3_PER_DAY,
    PRESSURE_CEILING_BAR,
    REGION_PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    PRESSURE_FLOOR_BAR,
    SOURCE_ASSUMPTION,
    SOURCE_DIAGNOSTIC,
    SOURCE_ORGANIZER,
    bhp_limits,
    constraint_source,
    source_key,
)

CONFIG_ROOT = Path(__file__).resolve().parents[4] / "config"


def _write(tmp_path: Path, infrastructure: dict[str, object]) -> Path:
    path = tmp_path / "case.json"
    path.write_text(
        json.dumps({"infrastructure": infrastructure}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_blocking_constraint_without_a_source_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, {BHP_PRODUCER_MIN_BAR: 70.0})
    with pytest.raises(CaseError) as error:
        load_case(path)
    assert source_key(BHP_PRODUCER_MIN_BAR) in str(error.value)


@pytest.mark.parametrize("key", BLOCKING_INFRASTRUCTURE_KEYS)
def test_every_blocking_key_names_its_own_source_field(key: str) -> None:
    values: dict[str, object] = {
        "water_supply_unlimited": True,
        "water_reinjection_fraction": 0.9,
        "water_reinjection_lag_steps": 1,
        EXTERNAL_WATER_M3_PER_DAY: 100.0,
        BHP_PRODUCER_MIN_BAR: 70.0,
        BHP_INJECTOR_MAX_BAR: 280.0,
        PRESSURE_FLOOR_BAR: 100.0,
        PRESSURE_CEILING_BAR: 200.0,
        REGION_PRESSURE_FLOOR_BAR: 100.0,
        REGION_PRESSURE_CEILING_BAR: 200.0,
    }
    with pytest.raises(CaseError) as error:
        constraints_from_json({"infrastructure": {key: values[key]}})
    assert source_key(key) in str(error.value)


def test_case_with_a_source_is_accepted_and_the_source_reaches_the_consumer(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        {
            BHP_PRODUCER_MIN_BAR: 70.0,
            source_key(BHP_PRODUCER_MIN_BAR): SOURCE_ORGANIZER,
            BHP_INJECTOR_MAX_BAR: 280.0,
            source_key(BHP_INJECTOR_MAX_BAR): SOURCE_ASSUMPTION,
        },
    )
    constraints = load_case(path)
    assert constraint_source(constraints, BHP_PRODUCER_MIN_BAR) == SOURCE_ORGANIZER
    assert constraint_source(constraints, BHP_INJECTOR_MAX_BAR) == SOURCE_ASSUMPTION
    assert constraints.case_path == str(path)


def test_diagnostic_constraint_may_omit_its_source(tmp_path: Path) -> None:
    path = _write(tmp_path, {COMPENSATION_MIN: 0.9, COMPENSATION_MAX: 1.1})
    constraints = load_case(path)
    assert constraint_source(constraints, COMPENSATION_MIN) is None


def test_diagnostic_source_is_kept_when_declared(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            COMPENSATION_MIN: 0.9,
            source_key(COMPENSATION_MIN): SOURCE_DIAGNOSTIC,
            COMPENSATION_MAX: 1.1,
            source_key(COMPENSATION_MAX): SOURCE_DIAGNOSTIC,
        },
    )
    assert constraint_source(load_case(path), COMPENSATION_MIN) == SOURCE_DIAGNOSTIC


def test_unknown_source_value_is_refused_by_the_case_loader(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            BHP_PRODUCER_MIN_BAR: 70.0,
            source_key(BHP_PRODUCER_MIN_BAR): "куратор",
        },
    )
    with pytest.raises(CaseError, match=source_key(BHP_PRODUCER_MIN_BAR)):
        load_case(path)


def test_source_without_its_constraint_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, {source_key(COMPENSATION_MIN): SOURCE_DIAGNOSTIC})
    with pytest.raises(CaseError, match=source_key(COMPENSATION_MIN)):
        load_case(path)


def test_source_keys_are_part_of_the_infrastructure_whitelist() -> None:
    assert source_key(BHP_PRODUCER_MIN_BAR) in INFRASTRUCTURE_KEYS
    assert source_key(COMPENSATION_MIN) in INFRASTRUCTURE_KEYS
    assert BHP_INJECTOR_MAX_BAR in INFRASTRUCTURE_KEYS


@pytest.mark.parametrize(
    "path", sorted(CONFIG_ROOT.glob("cases/*.json")) + [CONFIG_ROOT / "competition-constraints.json"]
)
def test_shipped_cases_still_load(path: Path) -> None:
    constraints = load_case(path)
    for key in BLOCKING_INFRASTRUCTURE_KEYS:
        if key in constraints.infrastructure:
            assert constraint_source(constraints, key) is not None


def test_shipped_base_case_declares_the_bhp_corridor() -> None:
    limits = bhp_limits(load_case(CONFIG_ROOT / "cases" / "base.json"))
    assert limits.producer_min_bar == pytest.approx(50.0)
    assert limits.injector_max_bar == pytest.approx(300.0)
    assert not limits.producer_min_defaulted
    assert not limits.injector_max_defaulted
