
from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from backend.contexts.policy.domain.policy import Theta

from backend.contexts.optimization.application.verification import (
    CandidateCheck,
    SurrogateVerdict,
    TruthVerdict,
    VerificationError,
    VerificationReport,
    run_verification_loop,
    trust_region_objective,
)
from tests.support.backend.paths import REPO_ROOT

ROOT = REPO_ROOT / "backend" / "contexts" / "optimization" / "application"

BOUNDS = {"x": (0.0, 100.0)}


def _theta(value: float = 1.0) -> Theta:
    return Theta(values={"x": value}, bounds=dict(BOUNDS))


class _Surrogate:

    def __init__(self, version: int = 1, *, bias: float = 0.0, centre: float = 0.0) -> None:
        self.version = version
        self.bias = bias
        self.centre = centre
        self.calls: list[Theta] = []

    def __call__(self, theta: Theta) -> SurrogateVerdict:
        self.calls.append(theta)
        x = theta.values["x"]
        return SurrogateVerdict(
            predicted_npv=100.0 * x + self.bias,
            ood_score=abs(x - self.centre) / 10.0,
        )


class _Truth:

    def __init__(self) -> None:
        self.calls: list[Theta] = []

    def __call__(self, theta: Theta) -> TruthVerdict:
        self.calls.append(theta)
        x = theta.values["x"]
        self.calls_count = len(self.calls)
        return TruthVerdict(
            npv=100.0 * x,
            run_id=f"run-{len(self.calls):04d}",
            canonical_schedule_hash="c" * 64,
        )


class _Retrainer:

    def __init__(self, produce: list[_Surrogate]) -> None:
        self.produce = produce
        self.observations: list[tuple[CandidateCheck, ...]] = []

    def __call__(self, observations: tuple[CandidateCheck, ...]) -> _Surrogate:
        self.observations.append(observations)
        return self.produce.pop(0)


def _tolerance(limit: float):

    def criterion(checks) -> bool:
        return all(abs(check.relative_deviation) <= limit for check in checks)

    return criterion


def _loop(**kwargs):
    defaults = dict(
        seed=7,
        initial_tau=1.0,
        runs_per_round=3,
        max_rounds=2,
        optimizer_evaluations_per_round=60,
    )
    defaults.update(kwargs)
    return run_verification_loop(**defaults)




def test_converged_round_expands_the_trust_region() -> None:
    surrogate = _Surrogate()
    report = _loop(
        surrogate=surrogate,
        truth=_Truth(),
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
    )

    first = report.rounds[0]
    assert first.converged is True
    assert first.next_tau > first.tau
    assert first.retrained is False


def test_diverged_round_contracts_the_region_and_retrains() -> None:

    surrogate = _Surrogate(version=1, bias=1_000_000.0)
    next_version = _Surrogate(version=2, bias=0.0)
    retrainer = _Retrainer([next_version])

    report = _loop(
        surrogate=surrogate,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.001),
        start_theta=_theta(),
        max_rounds=1,
    )

    first = report.rounds[0]
    assert first.converged is False
    assert first.next_tau < first.tau
    assert first.retrained is True
    assert len(retrainer.observations) == 1
    assert retrainer.observations[0] == first.checks


def test_retraining_happens_only_on_a_diverged_round() -> None:
    retrainer = _Retrainer([])
    _loop(
        surrogate=_Surrogate(),
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.5),
        start_theta=_theta(),
    )

    assert retrainer.observations == []


def test_number_of_runs_per_round_is_the_budget_not_a_guess() -> None:

    truth = _Truth()
    report = _loop(
        surrogate=_Surrogate(),
        truth=truth,
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        runs_per_round=2,
        max_rounds=3,
    )

    assert all(len(round_report.checks) <= 2 for round_report in report.rounds)
    assert len(truth.calls) == report.total_runs




def test_candidates_outside_the_region_never_reach_the_simulator() -> None:

    surrogate = _Surrogate(centre=0.0)
    truth = _Truth()
    tau = 1.0

    _loop(
        surrogate=surrogate,
        truth=truth,
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        initial_tau=tau,
        max_rounds=1,
    )

    assert truth.calls, "the ground truth was never called"
    for theta in truth.calls:
        assert theta.values["x"] <= 10.0 + 1e-9, theta.values


def test_trust_region_is_expressed_as_infeasibility_not_as_a_correction() -> None:

    surrogate = _Surrogate(centre=0.0)
    objective = trust_region_objective(surrogate, tau=1.0)

    inside = objective(_theta(5.0))
    outside = objective(_theta(50.0))

    assert inside.feasible is True
    assert inside.violations_by_scenario == ()

    assert outside.feasible is False
    assert outside.violations_by_scenario
    assert outside.violations_by_scenario[0].scenario_id == "trust_region"
    assert outside.objective == pytest.approx(100.0 * 50.0)


def test_provenance_binds_the_prediction_to_a_surrogate_version_and_tau() -> None:
    surrogate = _Surrogate(version=3)
    result = trust_region_objective(surrogate, tau=2.0)(_theta(1.0))

    assert result.provenance["surrogate_version"] == "3"
    assert float(result.provenance["tau"]) == pytest.approx(2.0)


def test_empty_trust_region_stops_the_loop_instead_of_pretending() -> None:

    surrogate = _Surrogate(centre=1_000.0)

    with pytest.raises(VerificationError, match="no rounds at all"):
        _loop(
            surrogate=surrogate,
            truth=_Truth(),
            retrain=_Retrainer([]),
            criterion=_tolerance(0.5),
            start_theta=_theta(),
            initial_tau=0.0,
        )




def test_table_covers_every_checked_candidate_in_order() -> None:

    truth = _Truth()
    report = _loop(
        surrogate=_Surrogate(),
        truth=truth,
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        max_rounds=3,
    )

    assert report.total_runs == len(truth.calls)
    assert [check.run_id for check in report.table] == [
        f"run-{i:04d}" for i in range(1, len(truth.calls) + 1)
    ]
    for check in report.table:
        assert check.predicted_npv is not None
        assert check.actual_npv is not None
        assert check.canonical_schedule_hash


def test_diverged_rounds_stay_in_the_table() -> None:

    surrogate = _Surrogate(version=1, bias=1_000_000.0)
    retrainer = _Retrainer(
        [
            _Surrogate(version=2, bias=1_000_000.0),
            _Surrogate(version=3, bias=1_000_000.0),
        ]
    )

    report = _loop(
        surrogate=surrogate,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.0),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.converged_rounds == 0
    assert report.total_runs > 0
    assert len(report.table) == sum(len(r.checks) for r in report.rounds)


def test_deviation_is_signed_prediction_minus_fact() -> None:
    check = CandidateCheck(
        round_index=0,
        theta=_theta(),
        predicted_npv=110.0,
        actual_npv=100.0,
        ood_score=0.0,
        tau=1.0,
        surrogate_version=1,
        run_id="run-0001",
        canonical_schedule_hash="c" * 64,
    )

    assert check.deviation == pytest.approx(10.0)
    assert check.relative_deviation == pytest.approx(0.1)


def test_zero_actual_npv_is_an_error_not_a_silent_ratio() -> None:
    check = CandidateCheck(
        round_index=0,
        theta=_theta(),
        predicted_npv=1.0,
        actual_npv=0.0,
        ood_score=0.0,
        tau=1.0,
        surrogate_version=1,
        run_id="run-0001",
        canonical_schedule_hash="c" * 64,
    )

    with pytest.raises(VerificationError):
        check.relative_deviation




def test_final_reevaluation_uses_the_latest_surrogate_version() -> None:

    first = _Surrogate(version=1, bias=1_000_000.0)
    second = _Surrogate(version=2, bias=1_000_000.0)
    third = _Surrogate(version=3, bias=0.0)
    retrainer = _Retrainer([second, third])

    report = _loop(
        surrogate=first,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.0),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.final_surrogate_version == 3
    assert third.calls, "the latest version was not called during re-evaluation"


def test_best_candidate_is_chosen_by_fact_not_by_prediction() -> None:

    report = _loop(
        surrogate=_Surrogate(),
        truth=_Truth(),
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.best.actual_npv == max(check.actual_npv for check in report.table)


def test_self_consistent_is_false_when_the_latest_model_disagrees() -> None:

    first = _Surrogate(version=1, bias=1_000_000.0)
    disagreeing = _Surrogate(version=2, bias=5_000_000.0)
    retrainer = _Retrainer([disagreeing])

    report = _loop(
        surrogate=first,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.001),
        start_theta=_theta(),
        max_rounds=1,
    )

    assert report.self_consistent is False
    assert isinstance(report.reevaluation, SurrogateVerdict)


def test_self_consistent_is_true_when_the_latest_model_reproduces_the_choice() -> None:
    report = _loop(
        surrogate=_Surrogate(),
        truth=_Truth(),
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.self_consistent is True


def test_report_carries_no_claimable_npv_field() -> None:

    names = {field.name for field in fields(VerificationReport)}
    forbidden = {
        "npv_methodology",
        "final_npv",
        "declared_npv",
        "submission_npv",
    }

    assert names & forbidden == set()


def test_module_never_builds_the_final_artifact() -> None:

    tree = ast.parse((ROOT / "verification.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)

    assert "FinalNpvArtifact" not in names




def test_zero_runs_per_round_is_rejected() -> None:
    with pytest.raises(VerificationError):
        _loop(
            surrogate=_Surrogate(),
            truth=_Truth(),
            retrain=_Retrainer([]),
            criterion=_tolerance(0.5),
            start_theta=_theta(),
            runs_per_round=0,
        )


def test_non_expanding_expansion_factor_is_rejected() -> None:
    with pytest.raises(VerificationError):
        _loop(
            surrogate=_Surrogate(),
            truth=_Truth(),
            retrain=_Retrainer([]),
            criterion=_tolerance(0.5),
            start_theta=_theta(),
            tau_expansion=1.0,
        )


def test_contraction_outside_the_unit_interval_is_rejected() -> None:
    for bad in (0.0, 1.0, 1.5):
        with pytest.raises(VerificationError):
            _loop(
                surrogate=_Surrogate(),
                truth=_Truth(),
                retrain=_Retrainer([]),
                criterion=_tolerance(0.5),
                start_theta=_theta(),
                tau_contraction=bad,
            )


def test_negative_ood_score_is_rejected() -> None:
    with pytest.raises(VerificationError):
        SurrogateVerdict(predicted_npv=1.0, ood_score=-0.1)


def test_truth_without_run_id_is_rejected() -> None:

    with pytest.raises(VerificationError):
        TruthVerdict(npv=1.0, run_id="", canonical_schedule_hash="c" * 64)
