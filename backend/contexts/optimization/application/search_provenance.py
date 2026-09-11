from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.contexts.constraints.infrastructure.constraints_io import constraints_hash


def build_search_provenance(
    *,
    env: Any,
    artifacts: Any,
    constraints: Any,
    constraints_path: Path,
    lambda_selection: Any,
    threshold_decision: Any,
    bhp_tolerance: Any,
    soft_penalty: bool,
    penalty_rate: float,
    search_cap: int,
    final_cap: int,
    seed: int,
    artifact_sha256: Any,
) -> dict[str, str]:
    return {
        "model_version": env.model.version,
        "lambda_window": f"{env.lambda_.window_start}..{env.lambda_.window_end}",
        "lambda_stability": f"{env.lambda_.stability:.3f}",
        "seed": str(seed),
        "runtime_artifact_source": artifacts.source,
        "feature_context_sha256": artifact_sha256(
            artifacts.feature_context, "feature_context"
        ),
        "constraints_hash": constraints_hash(constraints),
        "scenario_ood_version": env.scenario_ood.version if env.scenario_ood else "none",
        "npv_head_version": env.npv_head.version if env.npv_head else "none",
        "constraints_path": str(constraints_path),
        **lambda_selection.as_provenance(),
        **threshold_decision.as_provenance(),
        **bhp_tolerance.as_provenance(),
        "ood_soft_penalty": "true" if soft_penalty else "false",
        "ood_penalty_per_unit": repr(penalty_rate),
        "search_fixed_point_cap": str(search_cap),
        "final_fixed_point_cap": str(final_cap),
        "search_strategy": "cma-es",
        "policy_equilibrium": "not-claimed",
    }
