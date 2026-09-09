from __future__ import annotations

from typing import Callable

import pytest

from backend.core.contracts import Constraints, WellOutage
from backend.domain.configuration.constraints_io import (
    constraints_from_json,
    constraints_hash,
    constraints_to_json,
)


def _constraints_forward() -> Constraints:
    return Constraints(
        injection_limits={2026: 1000.0, 2027: 1100.0, 2028: 1200.0},
        liquid_limits={2026: 5000.0, 2027: 5100.0},
        production_floors={2026: 300.0},
        watercut_limits={2026: 0.9, 2027: 0.95},
        well_outages=(
            WellOutage(well="P-1", control_step_from=0, control_step_to=2),
            WellOutage(well="I-4", control_step_from=3, control_step_to=3),
        ),
        infrastructure={
            "water_reinjection_fraction": 0.8,
            "external_water_m3_per_day": 250.0,
            "compensation_scope": "field",
        },
    )


def _constraints_reversed() -> Constraints:
    return Constraints(
        injection_limits={2028: 1200.0, 2027: 1100.0, 2026: 1000.0},
        liquid_limits={2027: 5100.0, 2026: 5000.0},
        production_floors={2026: 300.0},
        watercut_limits={2027: 0.95, 2026: 0.9},
        well_outages=(
            WellOutage(well="P-1", control_step_from=0, control_step_to=2),
            WellOutage(well="I-4", control_step_from=3, control_step_to=3),
        ),
        infrastructure={
            "compensation_scope": "field",
            "external_water_m3_per_day": 250.0,
            "water_reinjection_fraction": 0.8,
        },
    )


def test_hash_is_hex_sha256() -> None:
    digest = constraints_hash(_constraints_forward())

    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_key_insertion_order_does_not_change_hash() -> None:
    forward = _constraints_forward()
    backward = _constraints_reversed()

    assert list(forward.injection_limits) != list(backward.injection_limits)
    assert list(forward.infrastructure) != list(backward.infrastructure)
    assert constraints_hash(forward) == constraints_hash(backward)


def test_hash_is_stable_across_calls() -> None:
    constraints = _constraints_forward()

    assert constraints_hash(constraints) == constraints_hash(constraints)


def test_hash_survives_json_round_trip() -> None:
    constraints = _constraints_forward()
    restored = constraints_from_json(constraints_to_json(constraints))

    assert constraints_hash(restored) == constraints_hash(constraints)


def test_empty_constraints_differ_from_populated() -> None:
    assert constraints_hash(Constraints()) != constraints_hash(_constraints_forward())


YearMaps = dict[str, dict[int, float]]
Mutation = Callable[[YearMaps], YearMaps]


def _bump(section: str, year: int, value: float) -> Mutation:
    def mutate(fields: YearMaps) -> YearMaps:
        return {**fields, section: {**fields[section], year: value}}

    return mutate


@pytest.mark.parametrize(
    "mutate",
    [
        _bump("injection_limits", 2026, 1000.5),
        _bump("liquid_limits", 2027, 5101.0),
        _bump("production_floors", 2026, 301.0),
        _bump("watercut_limits", 2026, 0.91),
    ],
    ids=["injection", "liquid", "floors", "watercut"],
)
def test_changing_any_year_value_changes_hash(mutate: Mutation) -> None:
    baseline = _constraints_forward()
    fields: YearMaps = {
        "injection_limits": dict(baseline.injection_limits),
        "liquid_limits": dict(baseline.liquid_limits),
        "production_floors": dict(baseline.production_floors),
        "watercut_limits": dict(baseline.watercut_limits),
    }
    changed = Constraints(
        well_outages=baseline.well_outages,
        infrastructure=dict(baseline.infrastructure),
        **mutate(fields),
    )

    assert constraints_hash(changed) != constraints_hash(baseline)


def test_changing_outage_changes_hash() -> None:
    baseline = _constraints_forward()
    changed = Constraints(
        injection_limits=dict(baseline.injection_limits),
        liquid_limits=dict(baseline.liquid_limits),
        production_floors=dict(baseline.production_floors),
        watercut_limits=dict(baseline.watercut_limits),
        well_outages=(
            WellOutage(well="P-1", control_step_from=0, control_step_to=3),
            WellOutage(well="I-4", control_step_from=3, control_step_to=3),
        ),
        infrastructure=dict(baseline.infrastructure),
    )

    assert constraints_hash(changed) != constraints_hash(baseline)


def test_changing_infrastructure_value_changes_hash() -> None:
    baseline = _constraints_forward()
    infrastructure = dict(baseline.infrastructure)
    infrastructure["water_reinjection_fraction"] = 0.81
    changed = Constraints(
        injection_limits=dict(baseline.injection_limits),
        liquid_limits=dict(baseline.liquid_limits),
        production_floors=dict(baseline.production_floors),
        watercut_limits=dict(baseline.watercut_limits),
        well_outages=baseline.well_outages,
        infrastructure=infrastructure,
    )

    assert constraints_hash(changed) != constraints_hash(baseline)
