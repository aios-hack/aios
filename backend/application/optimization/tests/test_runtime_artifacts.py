from backend.application.optimization.runtime_artifacts import resolve_runtime_artifacts


def test_default_runtime_is_the_installed_production_bundle() -> None:
    result = resolve_runtime_artifacts({})
    assert result.source == "default production bundle"
    assert result.checkpoint.name == "trajectory_ensemble.json"
    assert result.npv_head is not None
    assert result.npv_head.name == "npv_head.pt"
