from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.domain.robustness import (
    FragilityBattery,
    RegretReport,
    ScenarioOutcome,
    Split,
    covers_battery,
    holdout_view,
    optimization_view,
    scenario_of,
)

ROOT = Path(__file__).resolve().parent.parent


def outcomes_for(
    battery: FragilityBattery,
    baseline: float,
    ours_by_id: dict[str, float] | None = None,
) -> tuple[ScenarioOutcome, ...]:
    overrides = ours_by_id or {}
    return tuple(
        ScenarioOutcome(
            scenario_id=scenario.scenario_id,
            split=scenario.split,
            npv_ours=overrides.get(scenario.scenario_id, baseline),
            npv_scenario_baseline=baseline,
        )
        for scenario in battery.scenarios
    )


def test_regret_is_measured_against_the_scenario_baseline_not_the_nominal(
    battery: FragilityBattery,
) -> None:
    heavy_baseline = 100.0
    outcome = ScenarioOutcome(
        scenario_id=battery.dev()[0].scenario_id,
        split=Split.DEV,
        npv_ours=95.0,
        npv_scenario_baseline=heavy_baseline,
    )
    assert outcome.regret == pytest.approx(5.0)
    assert outcome.relative_regret == pytest.approx(0.05)


def test_report_is_feasible_when_every_dev_scenario_is_within_the_threshold(
    battery: FragilityBattery,
) -> None:
    report = RegretReport(
        outcomes=outcomes_for(battery, baseline=1000.0),
        threshold=0.1,
        battery_hash=battery.battery_hash(),
    )
    feasible, violations = optimization_view(report)
    assert feasible
    assert violations == ()


def test_a_single_dev_scenario_over_the_threshold_makes_it_infeasible(
    battery: FragilityBattery,
) -> None:
    culprit = battery.dev()[2].scenario_id
    report = RegretReport(
        outcomes=outcomes_for(battery, 1000.0, {culprit: 500.0}),
        threshold=0.1,
        battery_hash=battery.battery_hash(),
    )
    feasible, violations = optimization_view(report)
    assert not feasible
    assert [v.scenario_id for v in violations] == [culprit]
    assert violations[0].regret == pytest.approx(500.0)


def test_holdout_is_reported_separately_and_never_gates_the_optimizer(
    battery: FragilityBattery,
) -> None:
    culprit = battery.holdout()[0].scenario_id
    report = RegretReport(
        outcomes=outcomes_for(battery, 1000.0, {culprit: 100.0}),
        threshold=0.1,
        battery_hash=battery.battery_hash(),
    )
    dev_feasible, dev_violations = optimization_view(report)
    holdout_feasible, holdout_violations = holdout_view(report)
    assert dev_feasible
    assert dev_violations == ()
    assert not holdout_feasible
    assert [v.scenario_id for v in holdout_violations] == [culprit]


def test_breakdown_by_scenario_is_available_for_the_defence(
    battery: FragilityBattery,
) -> None:
    report = RegretReport(
        outcomes=outcomes_for(
            battery, 1000.0, {battery.dev()[0].scenario_id: 700.0}
        ),
        threshold=0.5,
        battery_hash=battery.battery_hash(),
    )
    breakdown = report.by_scenario(Split.DEV)
    assert len(breakdown) == len(battery.dev())
    assert report.worst(Split.DEV).scenario_id == battery.dev()[0].scenario_id


def test_report_covers_the_whole_battery(battery: FragilityBattery) -> None:
    report = RegretReport(
        outcomes=outcomes_for(battery, 1000.0),
        threshold=0.1,
        battery_hash=battery.battery_hash(),
    )
    assert covers_battery(report, battery)


def test_outcome_split_must_agree_with_the_battery(
    battery: FragilityBattery,
) -> None:
    mislabelled = ScenarioOutcome(
        scenario_id=battery.dev()[0].scenario_id,
        split=Split.HOLDOUT,
        npv_ours=1.0,
        npv_scenario_baseline=1.0,
    )
    with pytest.raises(ValueError, match="объявляет"):
        scenario_of(battery, mislabelled)


def test_negative_threshold_is_rejected(battery: FragilityBattery) -> None:
    with pytest.raises(ValueError, match="отрицателен"):
        RegretReport(
            outcomes=outcomes_for(battery, 1000.0),
            threshold=-0.1,
            battery_hash=battery.battery_hash(),
        )


def test_robustness_never_folds_into_a_scalar_objective() -> None:
    forbidden = {"penalty", "penalize", "штраф"}
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for word in forbidden:
            if word in text:
                offenders.append(f"{path.name}: {word}")
    assert offenders == [], (
        "устойчивость выражается ограничением, а не штрафом: " + "; ".join(offenders)
    )


def test_regret_module_exposes_no_weighted_sum_of_scenarios() -> None:
    tree = ast.parse((ROOT / "regret.py").read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert not {"aggregate", "weighted", "total_regret", "objective"} & names
