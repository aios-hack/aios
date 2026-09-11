from __future__ import annotations

from pathlib import Path

from backend.contexts.surrogate.application.ensemble import TrajectoryEnsemble
from tests.support.backend.paths import REPO_ROOT


def test_loads_installed_production_ensemble() -> None:
    root = REPO_ROOT
    manifest = root / "data" / "model-production" / "physical" / "trajectory_ensemble.json"
    if not manifest.is_file():
        return
    model = TrajectoryEnsemble.load(manifest)
    assert len(model.models) == 3
    assert sum(model.weights) == 1.0
    assert len(model.version) == 64
