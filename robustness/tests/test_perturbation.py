from __future__ import annotations

import pytest

from contracts import Constraints, WellOutage

from robustness import (
    InfrastructureLimit,
    InjectionCap,
    KIND_SOURCE,
    LiquidCap,
    ORGANIZER_KINDS,
    ProductionFloor,
    WatercutCap,
    WellsOut,
)


def test_every_organizer_kind_carries_its_source_wording() -> None:
    for kind in ORGANIZER_KINDS:
        assert KIND_SOURCE[kind]


def test_wells_out_appends_outages_without_touching_the_base() -> None:
    base = Constraints(
        well_outages=(
            WellOutage(well="P1", control_step_from=0, control_step_to=2),
        )
    )
    perturbed = WellsOut(
        wells=("P9", "P8"), control_step_from=10, control_step_to=16
    ).apply(base)
    assert len(base.well_outages) == 1
    assert len(perturbed.well_outages) == 3
    assert [o.well for o in perturbed.well_outages[1:]] == ["P8", "P9"]


def test_wells_out_rejects_an_empty_window() -> None:
    with pytest.raises(ValueError, match="пустое окно"):
        WellsOut(wells=("P1",), control_step_from=5, control_step_to=5)


def test_wells_out_rejects_no_wells() -> None:
    with pytest.raises(ValueError, match="без скважин"):
        WellsOut(wells=(), control_step_from=0, control_step_to=1)


def test_caps_only_tighten_an_existing_limit() -> None:
    base = Constraints(injection_limits={2010: 100.0})
    loosened = InjectionCap(limits_by_year={2010: 400.0}).apply(base)
    tightened = InjectionCap(limits_by_year={2010: 40.0}).apply(base)
    assert loosened.injection_limits[2010] == 100.0
    assert tightened.injection_limits[2010] == 40.0


def test_liquid_cap_adds_years_not_present_in_the_base() -> None:
    base = Constraints(liquid_limits={2010: 100.0})
    perturbed = LiquidCap(limits_by_year={2011: 80.0}).apply(base)
    assert perturbed.liquid_limits == {2010: 100.0, 2011: 80.0}


def test_production_floor_only_raises() -> None:
    base = Constraints(production_floors={2010: 50.0})
    lower = ProductionFloor(floors_by_year={2010: 10.0}).apply(base)
    higher = ProductionFloor(floors_by_year={2010: 70.0}).apply(base)
    assert lower.production_floors[2010] == 50.0
    assert higher.production_floors[2010] == 70.0


def test_watercut_cap_rejects_a_share_outside_the_unit_interval() -> None:
    with pytest.raises(ValueError, match="вне"):
        WatercutCap(limits_by_year={2010: 1.5})


def test_negative_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="отрицателен"):
        InjectionCap(limits_by_year={2010: -1.0})


def test_empty_limit_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="без единого года"):
        LiquidCap(limits_by_year={})


def test_infrastructure_limit_refuses_to_overwrite_an_existing_key() -> None:
    base = Constraints(infrastructure={"pipeline_liquid_m3_per_day": 100.0})
    with pytest.raises(ValueError, match="уже заняты"):
        InfrastructureLimit(
            entries={"pipeline_liquid_m3_per_day": 50.0}
        ).apply(base)


def test_perturbations_compose_in_declared_order() -> None:
    document = Constraints()
    for perturbation in (
        InjectionCap(limits_by_year={2010: 90.0}),
        InjectionCap(limits_by_year={2010: 60.0}),
    ):
        document = perturbation.apply(document)
    assert document.injection_limits[2010] == 60.0
