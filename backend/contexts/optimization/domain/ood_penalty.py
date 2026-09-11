from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    OutOfDomainScheduleError,
)

from backend.contexts.optimization.domain.errors import (
    ScheduleSearchError,
)
from backend.contexts.surrogate.domain.npv_economic_features import scenario_feature_vector
from backend.contexts.surrogate.domain.vectorize import build_features
from backend.contexts.robustness.domain.ood import Exceedance, OodScore, worst_offenders
from backend.contexts.robustness.domain.scenario_ood import ScenarioDensityDomain
import math


OOD_EXCEEDANCE_LIMIT = 5


def _scenario_ood_excess(
    model_input, model, domain: ScenarioDensityDomain | None
) -> tuple[float, str] | None:
    if domain is None:
        return None
    x, well_index = build_features(model_input, model.wells, scenario_context=False)
    vector = scenario_feature_vector(
        x, well_index, n_wells=len(model.wells), feature_set="economic"
    )
    score = domain.score(vector[: domain.feature_width])
    if score <= domain.threshold:
        return None
    return score, (
        f"the joint density of the schedule {score:.4g} is above the threshold "
        f"{domain.threshold:.4g} (quantile {domain.threshold_quantile} on validation)"
    )


def _enforce_scenario_ood(
    model_input, model, domain: ScenarioDensityDomain | None
) -> None:
    exceeded = _scenario_ood_excess(model_input, model, domain)
    if exceeded is None:
        return
    raise OutOfDomainScheduleError(*exceeded)


def exceedance_record(item: Exceedance) -> dict[str, object]:
    return {
        "feature": item.feature,
        "well": item.well,
        "control_step": int(item.control_step),
        "value": None if math.isnan(item.value) else float(item.value),
        "train_low": None if math.isnan(item.low) else float(item.low),
        "train_high": None if math.isnan(item.high) else float(item.high),
        "score": None if math.isinf(item.score) else float(item.score),
        "unbounded": bool(math.isinf(item.score)),
    }


def format_ood_exceedances(
    ood: OodScore, limit: int = OOD_EXCEEDANCE_LIMIT
) -> tuple[dict[str, object], ...]:
    if not ood.exceedances:
        return ()
    return tuple(exceedance_record(item) for item in worst_offenders(ood, limit))


def _ood_threshold_excess(
    ood: OodScore, threshold: float | None
) -> tuple[float, str, tuple[dict[str, object], ...]] | None:
    if threshold is None or ood.inside(threshold):
        return None
    worst = ood.worst
    description = (
        "unknown exceedance"
        if worst is None
        else (
            f"{worst.feature}, well {worst.well}, "
            f"step {worst.control_step}, value {worst.value:.6g}, "
            f"train [{worst.low:.6g}, {worst.high:.6g}]"
        )
    )
    return ood.score, description, format_ood_exceedances(ood)


def _enforce_ood_threshold(ood: OodScore, threshold: float | None) -> None:
    exceeded = _ood_threshold_excess(ood, threshold)
    if exceeded is None:
        return
    raise OutOfDomainScheduleError(*exceeded)


def ood_penalty_factor(excess: float, penalty_per_unit: float) -> float:
    if not math.isfinite(excess) or excess < 0.0:
        raise ScheduleSearchError(
            f"applicability domain exceedance {excess!r} is not finite or is negative: "
            "there is nothing to compute the soft penalty from"
        )
    if not math.isfinite(penalty_per_unit) or penalty_per_unit < 0.0:
        raise ScheduleSearchError(
            f"the soft penalty rate {penalty_per_unit!r} is not finite or is negative"
        )
    return math.exp(-penalty_per_unit * excess)


def apply_ood_penalty(npv: float, excess: float, penalty_per_unit: float) -> float:
    if not math.isfinite(npv):
        raise ScheduleSearchError(
            f"NPV {npv!r} is not finite: the applicability domain soft penalty does not apply"
        )
    factor = ood_penalty_factor(excess, penalty_per_unit)
    penalized = npv * factor if npv >= 0.0 else npv / factor
    if not math.isfinite(penalized):
        raise ScheduleSearchError(
            f"the soft penalty produced a non-finite NPV: npv={npv!r}, excess={excess!r}, "
            f"rate={penalty_per_unit!r}"
        )
    return penalized


def format_ood_worst(ood: OodScore) -> str | None:
    worst = ood.worst
    if worst is None:
        return None
    return f"{worst.feature}@{worst.well}:{worst.control_step}"


__all__ = [
    "OOD_EXCEEDANCE_LIMIT",
    "apply_ood_penalty",
    "exceedance_record",
    "format_ood_exceedances",
    "format_ood_worst",
    "ood_penalty_factor",
]
