from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    BhpToleranceError,
)
import json
import math
import os
from dataclasses import (
    dataclass,
)
from pathlib import Path
from typing import Mapping, Sequence
from backend.contexts.constraints.domain.constraints import Constraints, bhp_limits
from backend.contexts.schedule.domain.validate import ViolationKind
from backend.contexts.schedule.domain.validate import Violation


SURROGATE_NONBLOCKING_KINDS = frozenset(
    {
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
    }
)


BHP_KINDS = SURROGATE_NONBLOCKING_KINDS


SURROGATE_METRICS_FORMAT = "aios.surrogate-metrics.v2"


DEFAULT_SURROGATE_METRICS = "out/surrogate-metrics.json"


@dataclass(frozen=True, slots=True)
class BhpTolerance:
    delta_bar: float | None
    origin: str
    source: str
    n_states: int
    detail: str

    @property
    def measured(self) -> bool:
        return self.delta_bar is not None

    def as_provenance(self) -> dict[str, str]:
        return {
            "bhp_gate_delta_bar": (
                "unmeasured" if self.delta_bar is None else repr(self.delta_bar)
            ),
            "bhp_gate_delta_origin": self.origin,
            "bhp_gate_delta_source": self.source,
            "bhp_gate_delta_states": str(self.n_states),
            "bhp_gate_agreement": (
                "same-definition-as-submission"
                if self.measured
                else "documented-difference-search-lets-bhp-through"
            ),
            "bhp_gate_detail": self.detail,
        }


def _bhp_tolerance_decision(
    environ: Mapping[str, str] | None = None,
) -> BhpTolerance:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_BHP_GATE_DELTA_BAR")
    configured = env.get("AIOS_SURROGATE_METRICS_PATH")
    root = env.get("AIOS_PROJECT_ROOT")
    metrics_path = (
        Path(configured)
        if configured
        else (Path(root) if root else Path.cwd()) / DEFAULT_SURROGATE_METRICS
    )
    if override is not None:
        try:
            value = float(override)
        except ValueError as error:
            raise BhpToleranceError(
                f"AIOS_BHP_GATE_DELTA_BAR={override!r} — the BHP channel tolerance "
                "is given as a number in bar"
            ) from error
        if not math.isfinite(value) or value < 0.0:
            raise BhpToleranceError(
                f"AIOS_BHP_GATE_DELTA_BAR={override!r} — the tolerance must be "
                "finite and non-negative"
            )
        return BhpTolerance(
            delta_bar=value,
            origin="environment-override",
            source=str(metrics_path) if metrics_path.is_file() else "none",
            n_states=0,
            detail=(
                f"AIOS_BHP_GATE_DELTA_BAR={override!r} overrides the metrics report; "
                "the tolerance originates from an explicit operator override"
            ),
        )
    if configured and not metrics_path.is_file():
        raise BhpToleranceError(
            f"AIOS_SURROGATE_METRICS_PATH={configured} points at a missing "
            "surrogate metrics report"
        )
    if not metrics_path.is_file():
        return BhpTolerance(
            delta_bar=None,
            origin="unmeasured-report-absent",
            source="none",
            n_states=0,
            detail=(
                f"metrics report {metrics_path} was not read: the P95 error of the BHP "
                "channel is unmeasured and must not be invented. The previous "
                "behaviour is preserved — search lets BHP violations through, "
                "submission blocks them; the gate difference is documented by "
                "this note"
            ),
        )
    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BhpToleranceError(
            f"surrogate metrics report {metrics_path} is not readable: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != SURROGATE_METRICS_FORMAT:
        raise BhpToleranceError(
            f"unsupported surrogate metrics report: {metrics_path}"
        )
    manifold = payload.get("optimizer_manifold")
    channel = manifold.get("bhp_channel") if isinstance(manifold, dict) else None
    if not isinstance(channel, dict):
        raise BhpToleranceError(
            f"{metrics_path}: the report has no optimizer_manifold.bhp_channel — "
            "there is nothing to derive the BHP channel tolerance from"
        )
    if "unavailable" in channel:
        return BhpTolerance(
            delta_bar=None,
            origin="unmeasured-no-opm-response",
            source=str(metrics_path),
            n_states=0,
            detail=(
                f"{metrics_path}: {channel['unavailable']}. The previous behaviour is "
                "preserved — search lets BHP violations through, submission "
                "blocks them; the gate difference is documented by this note"
            ),
        )
    raw = channel.get("bhp_error_bar_p95")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise BhpToleranceError(
            f"{metrics_path}: bhp_error_bar_p95 is not a number — the tolerance is not derived"
        )
    value = float(raw)
    if not math.isfinite(value) or value < 0.0:
        raise BhpToleranceError(
            f"{metrics_path}: bhp_error_bar_p95={value} is not finite or is negative"
        )
    states = channel.get("n_states")
    if isinstance(states, bool) or not isinstance(states, int) or states < 1:
        raise BhpToleranceError(
            f"{metrics_path}: a BHP channel without a single measured state "
            "does not define a tolerance"
        )
    return BhpTolerance(
        delta_bar=value,
        origin="metrics-report-p95",
        source=str(metrics_path),
        n_states=states,
        detail=(
            f"δ={value} bar — P95 error of the BHP channel over {states} states from "
            f"{metrics_path}; a candidate is rejected when the predicted BHP "
            "exceeds the limit by more than δ"
        ),
    )


def bhp_exceedance_bar(violation: Violation, constraints: Constraints) -> float:
    value = violation.value
    if value is None or not math.isfinite(float(value)):
        raise BhpToleranceError(
            f"violation {violation.kind.value} without a measured bottomhole pressure: "
            "there is nothing to compute the limit exceedance from"
        )
    limits = bhp_limits(constraints)
    if violation.kind is ViolationKind.BHP_BELOW_PRODUCER_LIMIT:
        return max(0.0, float(limits.producer_min_bar) - float(value))
    if violation.kind is ViolationKind.BHP_ABOVE_INJECTOR_LIMIT:
        return max(0.0, float(value) - float(limits.injector_max_bar))
    raise BhpToleranceError(
        f"{violation.kind.value} is not a BHP channel violation, the tolerance does not apply"
    )


def surrogate_blocking_violations(
    violations: Sequence[Violation],
    constraints: Constraints,
    tolerance: BhpTolerance,
) -> tuple[Violation, ...]:
    kept: list[Violation] = []
    for item in violations:
        if item.kind not in BHP_KINDS:
            kept.append(item)
            continue
        if not tolerance.measured:
            continue
        if bhp_exceedance_bar(item, constraints) > tolerance.delta_bar:
            kept.append(item)
    return tuple(kept)


__all__ = [
    "BHP_KINDS",
    "BhpTolerance",
    "DEFAULT_SURROGATE_METRICS",
    "SURROGATE_METRICS_FORMAT",
    "SURROGATE_NONBLOCKING_KINDS",
    "bhp_exceedance_bar",
    "surrogate_blocking_violations",
]
