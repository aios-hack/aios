
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.policy.domain.policy import OptimizerResult, Theta

from backend.contexts.robustness.domain.battery import FragilityBattery, Split
from backend.contexts.robustness.domain.regret import holdout_view, optimization_view
from backend.contexts.robustness.domain.battery import Scenario
from backend.contexts.optimization.application.scenario_baseline import (
    BaselineSearch,
    RegretComputation,
    ScenarioBaselineError,
    compute_regret,
    evaluation_budget,
    scenario_baseline,
    scenario_seed,
    worst_scenarios,
)
from tests.support.backend.paths import REPO_ROOT

ROOT = REPO_ROOT / "backend" / "contexts" / "optimization" / "application"

BOUNDS = {"aggressiveness": (0.0, 100.0)}
BUDGET = 120


def _theta(value: float = 5.0) -> Theta:
    return Theta(values={"aggressiveness": value}, bounds=dict(BOUNDS))


class _CappedObjective:

    def __init__(self, cap: float) -> None:
        self.cap = cap
        self.calls: list[Theta] = []

    def __call__(self, theta: Theta) -> OptimizerResult:
        self.calls.append(theta)
        value = theta.values["aggressiveness"]
        reachable = min(value, self.cap)
        objective = 1_000.0 * reachable
        return OptimizerResult(
            objective=objective,
            feasible=True,
            violations_by_scenario=(),
            provenance={"cap": str(self.cap)},
        )


class _Factory:

    def __init__(self, cap_by_scenario: dict[str, float], default_cap: float = 50.0) -> None:
        self.cap_by_scenario = cap_by_scenario
        self.default_cap = default_cap
        self.seen: list[tuple[str, Constraints]] = []
        self.objectives: dict[str, _CappedObjective] = {}

    def __call__(self, constraints: Constraints, scenario: Scenario) -> _CappedObjective:
        self.seen.append((scenario.scenario_id, constraints))
        objective = _CappedObjective(
            self.cap_by_scenario.get(scenario.scenario_id, self.default_cap)
        )
        self.objectives[scenario.scenario_id] = objective
        return objective




def test_baseline_is_produced_by_re_optimizing_theta_under_the_scenario(
    battery: FragilityBattery,
) -> None:

    scenario = battery.dev()[0]
    factory = _Factory({scenario.scenario_id: 40.0})

    search, ours = scenario_baseline(
        scenario,
        factory,
        _theta(value=5.0),
        battery_seed=battery.seed,
        max_evaluations=BUDGET,
    )

    assert isinstance(search, BaselineSearch)
    assert search.evaluations > 1, "the baseline must be a search, not a single evaluation"
    assert search.theta.values["aggressiveness"] > _theta().values["aggressiveness"]
    assert search.npv > ours


def test_factory_receives_the_perturbed_constraints_not_the_base(
    battery: FragilityBattery,
) -> None:

    scenario = battery.dev()[0]
    factory = _Factory({})
    base = Constraints()

    scenario_baseline(
        scenario,
        factory,
        _theta(),
        battery_seed=battery.seed,
        max_evaluations=BUDGET,
        base_constraints=base,
    )

    assert len(factory.seen) == 1
    seen_id, seen_constraints = factory.seen[0]
    assert seen_id == scenario.scenario_id
    assert seen_constraints == scenario.constraints(base)
    assert seen_constraints != base


def test_our_npv_is_also_evaluated_inside_the_scenario(
    battery: FragilityBattery,
) -> None:

    scenario = battery.dev()[0]
    factory = _Factory({scenario.scenario_id: 3.0})

    _, ours = scenario_baseline(
        scenario,
        factory,
        _theta(value=5.0),
        battery_seed=battery.seed,
        max_evaluations=BUDGET,
    )

    assert ours == pytest.approx(3_000.0)


def test_optimizer_is_run_once_per_scenario(battery: FragilityBattery) -> None:

    factory = _Factory({})
    computation = compute_regret(
        battery,
        factory,
        _theta(),
        threshold=0.1,
        max_evaluations_per_scenario=BUDGET,
    )

    assert len(factory.objectives) == len(battery.scenarios)
    assert len(computation.searches) == len(battery.scenarios)
    assert computation.total_evaluations >= len(battery.scenarios)




def test_a_scenario_that_hurts_everyone_equally_gives_zero_regret(
    battery: FragilityBattery,
) -> None:

    scenario = battery.dev()[0]
    factory = _Factory({scenario.scenario_id: 2.0})

    search, ours = scenario_baseline(
        scenario,
        factory,
        _theta(value=5.0),
        battery_seed=battery.seed,
        max_evaluations=BUDGET,
    )

    assert ours == pytest.approx(2_000.0)
    assert search.npv - ours == pytest.approx(0.0)


def test_a_scenario_where_a_better_plan_exists_gives_positive_regret(
    battery: FragilityBattery,
) -> None:
    scenario = battery.dev()[0]
    factory = _Factory({scenario.scenario_id: 80.0})

    search, ours = scenario_baseline(
        scenario,
        factory,
        _theta(value=5.0),
        battery_seed=battery.seed,
        max_evaluations=BUDGET,
    )

    assert search.npv - ours > 0.0




def test_report_covers_every_scenario_by_name(battery: FragilityBattery) -> None:

    computation = compute_regret(
        battery,
        _Factory({}),
        _theta(),
        threshold=0.5,
        max_evaluations_per_scenario=BUDGET,
    )

    reported = {outcome.scenario_id for outcome in computation.report.outcomes}
    assert reported == {scenario.scenario_id for scenario in battery.scenarios}

    for scenario in battery.scenarios:
        search = computation.search_of(scenario.scenario_id)
        assert search.split is scenario.split


def test_worst_scenarios_are_ordered_by_relative_regret(
    battery: FragilityBattery,
) -> None:
    dev = battery.dev()
    caps = {dev[0].scenario_id: 90.0, dev[1].scenario_id: 6.0}
    computation = compute_regret(
        battery,
        _Factory(caps, default_cap=10.0),
        _theta(value=5.0),
        threshold=0.5,
        max_evaluations_per_scenario=BUDGET,
    )

    worst = worst_scenarios(computation, Split.DEV, limit=2)

    assert len(worst) == 2
    assert worst[0].relative_regret >= worst[1].relative_regret
    assert worst[0].scenario_id == dev[0].scenario_id


def test_dev_and_holdout_stay_separate(battery: FragilityBattery) -> None:

    computation = compute_regret(
        battery,
        _Factory({}),
        _theta(),
        threshold=0.5,
        max_evaluations_per_scenario=BUDGET,
    )

    dev_ids = {outcome.scenario_id for outcome in computation.report.of(Split.DEV)}
    holdout_ids = {
        outcome.scenario_id for outcome in computation.report.of(Split.HOLDOUT)
    }

    assert dev_ids
    assert holdout_ids
    assert dev_ids.isdisjoint(holdout_ids)




def test_result_is_a_constraint_pair_not_a_scalar(battery: FragilityBattery) -> None:

    dev = battery.dev()
    computation = compute_regret(
        battery,
        _Factory({dev[0].scenario_id: 90.0}, default_cap=5.0),
        _theta(value=5.0),
        threshold=0.01,
        max_evaluations_per_scenario=BUDGET,
    )

    feasible, violations = optimization_view(computation.report)

    assert feasible is False
    assert violations
    assert dev[0].scenario_id in {violation.scenario_id for violation in violations}
    for violation in violations:
        assert violation.what


def test_holdout_view_is_available_separately(battery: FragilityBattery) -> None:
    computation = compute_regret(
        battery,
        _Factory({}),
        _theta(),
        threshold=0.5,
        max_evaluations_per_scenario=BUDGET,
    )

    feasible, violations = holdout_view(computation.report)

    assert isinstance(feasible, bool)
    assert isinstance(violations, tuple)


def test_module_never_sums_over_the_battery() -> None:

    path = ROOT / "scenario_baseline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "sum":
            continue
        dumped = ast.dump(node)
        assert "regret" not in dumped, "regret was folded by summation"
        assert "npv" not in dumped, "scenario NPVs were folded by summation"




def test_underpowered_baseline_is_flagged_not_clamped(
    battery: FragilityBattery,
) -> None:

    scenario = battery.dev()[0]
    factory = _Factory({scenario.scenario_id: 100.0})

    search, ours = scenario_baseline(
        scenario,
        factory,
        _theta(value=99.0),
        battery_seed=battery.seed,
        max_evaluations=4,
    )

    assert search.underpowered is (search.npv < ours)
    if search.underpowered:
        assert search.stop_reason


def test_computation_collects_underpowered_scenarios(
    battery: FragilityBattery,
) -> None:
    computation = compute_regret(
        battery,
        _Factory({}),
        _theta(),
        threshold=0.5,
        max_evaluations_per_scenario=BUDGET,
    )

    assert isinstance(computation.underpowered_scenarios, tuple)
    assert set(computation.underpowered_scenarios) <= {
        scenario.scenario_id for scenario in battery.scenarios
    }




def test_scenario_seed_is_derived_from_the_identifier_not_the_index() -> None:

    assert scenario_seed(11, "inj_cap_2015") == scenario_seed(11, "inj_cap_2015")
    assert scenario_seed(11, "inj_cap_2015") != scenario_seed(11, "inj_cap_2016")
    assert scenario_seed(11, "inj_cap_2015") != scenario_seed(12, "inj_cap_2015")


def test_same_battery_seed_gives_the_same_regret(battery: FragilityBattery) -> None:
    first = compute_regret(
        battery, _Factory({}), _theta(), threshold=0.5, max_evaluations_per_scenario=BUDGET
    )
    second = compute_regret(
        battery, _Factory({}), _theta(), threshold=0.5, max_evaluations_per_scenario=BUDGET
    )

    assert first.report.by_scenario(Split.DEV) == second.report.by_scenario(Split.DEV)
    assert [search.seed for search in first.searches] == [
        search.seed for search in second.searches
    ]


def test_report_is_bound_to_the_battery_it_was_measured_on(
    battery: FragilityBattery,
) -> None:
    computation = compute_regret(
        battery, _Factory({}), _theta(), threshold=0.5, max_evaluations_per_scenario=BUDGET
    )

    assert computation.report.battery_hash == battery.battery_hash()




def test_zero_budget_is_rejected(battery: FragilityBattery) -> None:
    with pytest.raises(ScenarioBaselineError):
        scenario_baseline(
            battery.dev()[0],
            _Factory({}),
            _theta(),
            battery_seed=battery.seed,
            max_evaluations=0,
        )


def test_evaluation_budget_is_computed_up_front(battery: FragilityBattery) -> None:

    assert evaluation_budget(battery, 200) == len(battery.scenarios) * 200
    with pytest.raises(ScenarioBaselineError):
        evaluation_budget(battery, 0)


def test_unknown_scenario_lookup_is_rejected(battery: FragilityBattery) -> None:
    computation = compute_regret(
        battery, _Factory({}), _theta(), threshold=0.5, max_evaluations_per_scenario=BUDGET
    )

    with pytest.raises(ScenarioBaselineError):
        computation.search_of("no such scenario")


def test_zero_limit_for_worst_scenarios_is_rejected(battery: FragilityBattery) -> None:
    computation = compute_regret(
        battery, _Factory({}), _theta(), threshold=0.5, max_evaluations_per_scenario=BUDGET
    )

    with pytest.raises(ScenarioBaselineError):
        worst_scenarios(computation, Split.DEV, limit=0)


def test_computation_keeps_the_nominal_theta_it_was_measured_for(
    battery: FragilityBattery,
) -> None:

    theta = _theta(value=7.0)
    computation = compute_regret(
        battery, _Factory({}), theta, threshold=0.5, max_evaluations_per_scenario=BUDGET
    )

    assert isinstance(computation, RegretComputation)
    assert computation.nominal_theta == theta
