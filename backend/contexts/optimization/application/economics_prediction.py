from __future__ import annotations

from backend.contexts.optimization.domain.search_environment import (
    SearchEnvironment,
)
from backend.contexts.optimization.domain.provenance import (
    _validate_npv_scoring_is_unambiguous,
)
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.economics.application.base_case import analyze_base_case


def predict_economics(env: SearchEnvironment, model_input, response: ResponseArtifact) -> dict[str, float]:
    physical = analyze_base_case(
        response, env.deck_dates, env.t0_deck_date_index, env.normatives, env.policies,
    ).npv_methodology
    if env.npv_head is None:
        blended = env.npv_calibration.apply(physical) if env.npv_calibration is not None else physical
        return {"physical": physical, "blended": blended}
    _validate_npv_scoring_is_unambiguous(env.npv_head, env.npv_calibration)
    direct = env.npv_head.predict(model_input)
    weight = float(getattr(env.npv_head, "physical_npv_weight", 0.0))
    return {"direct": direct, "physical": physical, "blended": (1.0 - weight) * direct + weight * physical}


__all__ = [
    "predict_economics",
]
