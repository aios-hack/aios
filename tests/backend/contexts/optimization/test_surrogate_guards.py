"""Guard behavior only; synthetic counts are never model-quality evidence."""
from pathlib import Path
import pytest

from backend.contexts.optimization.application.environment import (
    _enforce_physics,
    PhysicallyImpossibleScheduleError,
)
from backend.contexts.optimization.infrastructure.artifacts import RuntimeArtifacts
from backend.contexts.optimization.application import search_use_case as search_run
from backend.contexts.surrogate.domain.physics_checks import PhysicsReport, Invariant


def _report(counts):
    return PhysicsReport(counts=counts, examples=(), evaluated=tuple(Invariant), skipped={}, n_nodes=1, n_wells=1)


@pytest.mark.parametrize("count", [1, 58, 61])
def test_baseline_counts_never_excuse_a_blocking_prediction(count):
    with pytest.raises(PhysicallyImpossibleScheduleError) as error:
        _enforce_physics(_report({"SHUT_WELL_FLOW": count}), True, {"SHUT_WELL_FLOW": 58})
    assert error.value.counts == {"SHUT_WELL_FLOW": count}


def test_bhp_warning_remains_diagnostic():
    _enforce_physics(_report({"BHP_LIMIT": 9}), True)


def test_search_refuses_to_start_without_scenario_guard(monkeypatch):
    artifacts = RuntimeArtifacts(checkpoint=Path("unused"), feature_context=Path("unused"), npv_head=None, source="test")
    monkeypatch.setattr(search_run, "resolve_runtime_artifacts", lambda: artifacts)
    with pytest.raises(search_run.SearchRunError, match="requires a versioned scenario OOD"):
        search_run.run_search(budget=1)
