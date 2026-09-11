from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core.contracts import CompensationPolicy, Constraints
from backend.contexts.showcase.application.exporters.compensation_view import (
    COMPENSATION_BASIS_SURFACE,
    COMPENSATION_NORM_MAX,
    COMPENSATION_NORM_MIN,
    COMPENSATION_SOURCE_DIAGNOSTIC,
    compensation_norm,
    reservoir_compensation,
)
from tests.support.backend.showcase_fixtures import make_synthetic_artifact
from backend.contexts.showcase.application.exporters.timeline import build_timeline

DEFAULT_POLICY = CompensationPolicy(None, None, "diagnostic", "field_and_groups")


def _timeline(**kwargs: object) -> dict[str, object]:
    artifact = make_synthetic_artifact()
    densities = {well: 900.0 for well in artifact.schedule.meta.wells}
    return build_timeline(artifact, densities, **kwargs)


def test_norm_carries_diagnostic_source() -> None:
    norm = compensation_norm(DEFAULT_POLICY)
    assert norm["source"] == COMPENSATION_SOURCE_DIAGNOSTIC
    assert norm["min"] == COMPENSATION_NORM_MIN
    assert norm["max"] == COMPENSATION_NORM_MAX


def test_diagnostic_corridor_is_ours_not_the_organiser_band() -> None:
    norm = compensation_norm(DEFAULT_POLICY)
    assert (norm["min"], norm["max"]) == (0.85, 1.15)
    assert (norm["min"], norm["max"]) != (1.20, 1.46)


def test_norm_defaults_to_non_blocking_diagnostic_enforcement() -> None:
    norm = compensation_norm(DEFAULT_POLICY)
    assert norm["enforcement"] == "diagnostic"
    assert norm["scope"] == "field_and_groups"


def test_policy_bounds_and_mode_override_defaults() -> None:
    policy = CompensationPolicy(1.20, 1.46, "hard", "field")
    norm = compensation_norm(policy)
    assert (norm["min"], norm["max"]) == (1.20, 1.46)
    assert norm["enforcement"] == "hard"
    assert norm["scope"] == "field"


def test_norm_declares_surface_basis() -> None:
    assert compensation_norm(DEFAULT_POLICY)["basis"] == COMPENSATION_BASIS_SURFACE


def test_reservoir_compensation_is_none_without_factors() -> None:
    assert reservoir_compensation(100.0, 90.0, None) is None
    assert reservoir_compensation(100.0, 90.0, {}) is None
    assert reservoir_compensation(100.0, 90.0, {"liquid": 1.2}) is None


def test_reservoir_compensation_uses_both_volume_factors() -> None:
    value = reservoir_compensation(100.0, 90.0, {"liquid": 1.2, "water": 1.02})
    assert value == pytest.approx(90.0 * 1.02 / (100.0 * 1.2))


def test_reservoir_compensation_rejects_non_positive_factors() -> None:
    assert reservoir_compensation(100.0, 90.0, {"liquid": 0.0, "water": 1.0}) is None
    assert reservoir_compensation(100.0, 90.0, {"liquid": 1.0, "water": -1.0}) is None


def test_reservoir_compensation_is_none_without_withdrawal() -> None:
    assert reservoir_compensation(0.0, 90.0, {"liquid": 1.2, "water": 1.02}) is None


def test_timeline_publishes_corridor_with_its_source() -> None:
    norms = _timeline()["field_norms"]
    band = norms["compensation"]
    assert band["source"] == COMPENSATION_SOURCE_DIAGNOSTIC
    assert band["min"] == 0.85
    assert band["max"] == 1.15
    assert band["basis"] == COMPENSATION_BASIS_SURFACE


def test_timeline_step_reports_surface_compensation() -> None:
    field = _timeline()["steps"][0]["field"]
    assert field["compensation_surface"] == field["compensation"]
    assert field["compensation_defined"] is True


def test_timeline_omits_reservoir_value_when_not_convertible() -> None:
    field = _timeline()["steps"][0]["field"]
    assert "compensation_reservoir" in field
    assert field["compensation_reservoir"] is None


def test_timeline_reports_reservoir_value_when_factors_given() -> None:
    field = _timeline(reservoir_factors={"liquid": 1.2, "water": 1.02})["steps"][0][
        "field"
    ]
    surface = field["compensation_surface"]
    reservoir = field["compensation_reservoir"]
    assert reservoir is not None
    assert reservoir == pytest.approx(surface * 1.02 / 1.2, rel=1e-4)


def test_terminal_step_reports_no_compensation_at_all() -> None:
    steps = _timeline()["steps"]
    terminal = [step for step in steps if step["terminal"]]
    assert terminal
    field = terminal[0]["field"]
    assert field["compensation"] is None
    assert field["compensation_surface"] is None
    assert field["compensation_reservoir"] is None
    assert field["compensation_defined"] is None


def test_zero_withdrawal_leaves_compensation_undefined_not_zero() -> None:
    artifact = make_synthetic_artifact()
    emptied = replace(
        artifact,
        interval_response=tuple(
            replace(row, liquid_volume_delta=0.0, oil_mass_delta=0.0)
            for row in artifact.interval_response
        ),
    )
    densities = {well: 900.0 for well in emptied.schedule.meta.wells}
    field = build_timeline(emptied, densities)["steps"][0]["field"]
    assert field["compensation"] is None
    assert field["compensation_defined"] is False
    assert field["compensation"] != 0


def test_corridor_follows_constraints_when_declared() -> None:
    artifact = make_synthetic_artifact()
    tightened = replace(
        artifact,
        constraints=Constraints(
            infrastructure={
                "compensation_min": 1.20,
                "compensation_max": 1.46,
                "compensation_enforcement": "hard",
                "compensation_scope": "field",
            }
        ),
    )
    densities = {well: 900.0 for well in tightened.schedule.meta.wells}
    band = build_timeline(tightened, densities)["field_norms"]["compensation"]
    assert (band["min"], band["max"]) == (1.20, 1.46)
    assert band["enforcement"] == "hard"
    assert band["scope"] == "field"
    assert band["source"] == COMPENSATION_SOURCE_DIAGNOSTIC
