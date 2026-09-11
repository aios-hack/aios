from __future__ import annotations

from backend.contexts.optimization.application.economics_prediction import predict_economics
from backend.contexts.optimization.domain.search_environment import SearchEnvironment

from backend.contexts.optimization.domain.errors import (
    EnsembleSpreadError,
)
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput
import hashlib
import math
from typing import (
    Sequence,
)
from backend.core.contracts import (
    ResponseArtifact,
    Schedule,
    canonical_bytes,
    hash_schedule,
)
from backend.contexts.surrogate.application.adapter import ResponseAdapter
from backend.contexts.surrogate.application.ensemble import TrajectoryEnsemble
from backend.contexts.surrogate.application.model import TrajectorySurrogate


def ensemble_members(
    model: TrajectorySurrogate | TrajectoryEnsemble,
) -> tuple[TrajectorySurrogate, ...]:
    members = getattr(model, "models", None)
    if members is None:
        return ()
    return tuple(members)


def _member_outputs(
    model: TrajectoryEnsemble, model_input
) -> tuple[RawModelOutput, ...]:
    members = ensemble_members(model)
    if len(members) < 2:
        raise EnsembleSpreadError(
            "разброс ансамбля считается по членам, а их меньше двух"
        )
    return tuple(member._predict_output(model_input) for member in members)


def _total_oil_mass(output: RawModelOutput) -> float:
    return math.fsum(node.oil_mass_delta for node in output.nodes)


def spread_bracket(
    outputs: Sequence[RawModelOutput],
) -> tuple[RawModelOutput, RawModelOutput]:
    if len(outputs) < 2:
        raise EnsembleSpreadError(
            "крайние члены ансамбля выбираются минимум из двух прогнозов"
        )
    ranked = sorted(outputs, key=_total_oil_mass)
    return ranked[0], ranked[-1]


def _npv_of_output(
    env: SearchEnvironment,
    adapter: ResponseAdapter,
    schedule: Schedule,
    model_input,
    output: RawModelOutput,
    tag: str,
) -> float:
    states, intervals = adapter.adapt(
        output, schedule, env.real_history, env.control_dates
    )
    identity = {
        "model_version": env.model.version,
        "schedule_hash": hash_schedule(schedule),
        "ensemble_member": tag,
    }
    response = ResponseArtifact(
        source_run_id=f"surrogate-member:{env.model.version[:12]}",
        response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
        state_at_date=states,
        interval_response=intervals,
    )
    return float(predict_economics(env, model_input, response)["blended"])


def ensemble_npv_sigma(
    env: SearchEnvironment,
    adapter: ResponseAdapter,
    schedule: Schedule,
    model_input,
) -> float | None:
    if not isinstance(env.model, TrajectoryEnsemble):
        return None
    low_output, high_output = spread_bracket(_member_outputs(env.model, model_input))
    npv_low = _npv_of_output(
        env, adapter, schedule, model_input, low_output, "low"
    )
    npv_high = _npv_of_output(
        env, adapter, schedule, model_input, high_output, "high"
    )
    sigma = abs(npv_high - npv_low) / 2.0
    if not math.isfinite(sigma):
        raise EnsembleSpreadError(
            "разброс ЧДД по членам ансамбля не конечен: "
            f"npv_low={npv_low!r}, npv_high={npv_high!r}"
        )
    return sigma


__all__ = [
    "ensemble_members",
    "ensemble_npv_sigma",
    "spread_bracket",
]
