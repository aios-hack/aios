from __future__ import annotations

import pytest

from aios_backend.core.contracts import Constraints

from aios_backend.domain.robustness import (
    BatteryBasis,
    FragilityBattery,
    InjectionCap,
    ORGANIZER_KINDS,
    PerturbationKind,
    Scenario,
    Split,
    battery_of,
    coverage_report,
    default_battery,
    default_scenarios,
    split_by_declaration,
)


def test_battery_covers_every_perturbation_type_named_by_organizers(
    battery: FragilityBattery,
) -> None:
    assert set(battery.kinds()) == set(ORGANIZER_KINDS)


def test_dev_and_holdout_are_both_non_empty(battery: FragilityBattery) -> None:
    assert battery.dev()
    assert battery.holdout()


def test_dev_and_holdout_do_not_share_a_single_scenario(
    battery: FragilityBattery,
) -> None:
    dev_ids = {s.scenario_id for s in battery.dev()}
    holdout_ids = {s.scenario_id for s in battery.holdout()}
    assert dev_ids & holdout_ids == set()
    assert len(dev_ids) + len(holdout_ids) == len(battery.scenarios)


def test_holdout_covers_types_seen_in_dev_but_not_the_same_documents(
    battery: FragilityBattery,
) -> None:
    report = coverage_report(battery)
    assert set(report["holdout"]) <= set(report["dev"])
    dev_documents = {
        s.scenario_id: s.constraints() for s in battery.dev()
    }
    for scenario in battery.holdout():
        assert scenario.constraints() not in dev_documents.values()


def test_battery_without_holdout_is_rejected(basis: BatteryBasis) -> None:
    dev_only = tuple(
        Scenario(
            scenario_id=s.scenario_id,
            split=Split.DEV,
            description=s.description,
            perturbations=s.perturbations,
        )
        for s in default_scenarios(basis)
    )
    with pytest.raises(ValueError, match="holdout"):
        battery_of(dev_only, seed=1, version="broken")


def test_battery_missing_an_organizer_type_is_rejected(
    basis: BatteryBasis,
) -> None:
    only_injection = (
        Scenario(
            scenario_id="dev-one",
            split=Split.DEV,
            description="дефицит воды",
            perturbations=(InjectionCap(limits_by_year={2010: 10.0}),),
        ),
        Scenario(
            scenario_id="holdout-one",
            split=Split.HOLDOUT,
            description="дефицит воды сильнее",
            perturbations=(InjectionCap(limits_by_year={2011: 5.0}),),
        ),
    )
    with pytest.raises(ValueError, match="типы возмущений"):
        battery_of(only_injection, seed=1, version="narrow")


def test_scenario_produces_a_serializable_constraints_document(
    battery: FragilityBattery,
) -> None:
    documents = battery.constraints_by_scenario()
    assert len(documents) == len(battery.scenarios)
    for document in documents.values():
        assert isinstance(document, Constraints)


def test_every_scenario_differs_from_the_empty_document(
    battery: FragilityBattery,
) -> None:
    empty = Constraints()
    for scenario in battery.scenarios:
        assert scenario.constraints() != empty


def test_battery_needs_no_run_to_be_built(battery: FragilityBattery) -> None:
    assert battery.constraints_by_scenario()
    assert battery.battery_hash()


def test_battery_hash_is_deterministic(basis: BatteryBasis) -> None:
    first = default_battery(basis, seed=5)
    second = default_battery(basis, seed=5)
    assert first.battery_hash() == second.battery_hash()


def test_battery_hash_changes_with_seed_and_version(basis: BatteryBasis) -> None:
    base = default_battery(basis, seed=5)
    other_seed = default_battery(basis, seed=6)
    other_version = battery_of(base.scenarios, seed=5, version="battery-2")
    assert base.battery_hash() != other_seed.battery_hash()
    assert base.battery_hash() != other_version.battery_hash()


def test_duplicate_scenario_ids_are_rejected(battery: FragilityBattery) -> None:
    duplicated = battery.scenarios + (battery.scenarios[0],)
    with pytest.raises(ValueError, match="повторяющиеся"):
        battery_of(duplicated, seed=1, version="dup")


def test_scenario_without_perturbations_is_rejected() -> None:
    with pytest.raises(ValueError, match="номинальным"):
        Scenario(
            scenario_id="empty",
            split=Split.DEV,
            description="ничего не меняем",
            perturbations=(),
        )


def test_split_by_declaration_moves_named_scenarios_to_holdout(
    basis: BatteryBasis,
) -> None:
    scenarios = default_scenarios(basis)
    resolved = split_by_declaration(scenarios, ("liquid-cap-late",))
    moved = {s.scenario_id for s in resolved if s.split is Split.HOLDOUT}
    assert moved == {"liquid-cap-late"}


def test_split_by_declaration_rejects_unknown_scenario(
    basis: BatteryBasis,
) -> None:
    with pytest.raises(ValueError, match="отсутствующие"):
        split_by_declaration(default_scenarios(basis), ("no-such-scenario",))


def test_kind_of_each_scenario_is_declared(battery: FragilityBattery) -> None:
    for scenario in battery.scenarios:
        assert scenario.kinds
        for kind in scenario.kinds:
            assert isinstance(kind, PerturbationKind)
