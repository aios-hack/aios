from __future__ import annotations

from backend.contexts.surrogate.domain.npv_block_head import (
    BlockKernelNpvHead,
)
from backend.contexts.robustness.domain.scenario_ood import ScenarioDensityDomain
from backend.contexts.surrogate.domain.npv_calibration import NpvCalibration
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput
from dataclasses import (
    dataclass,
)
from datetime import date
from types import MappingProxyType
from typing import (
    Mapping,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.connectivity.domain.connectivity import Groups, Lambda
from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.policy.domain.flags import (
    RuleFlags,
)
from backend.contexts.surrogate.domain.predictor import TrajectoryPredictor
from backend.contexts.surrogate.domain.model_z_artifact import ModelZFeatureArtifact
from backend.contexts.surrogate.domain.npv_head import ScenarioNpvHead


@dataclass(frozen=True, slots=True)
class SearchEnvironment:
    base_schedule: Schedule
    real_history: ResponseArtifact
    normatives: NormativeSet
    policies: Policies
    oil_density_t_per_m3: float
    feature_context: ModelZFeatureArtifact
    model: TrajectoryPredictor
    control_dates: tuple[date, ...]
    deck_dates: tuple[date, ...]
    t0_deck_date_index: int
    groups: Groups
    lambda_: Lambda
    constraints: Constraints
    flags: RuleFlags
    npv_head: ScenarioNpvHead | BlockKernelNpvHead | None = None
    scenario_ood: ScenarioDensityDomain | None = None
    npv_calibration: NpvCalibration | None = None
    physics_gate: bool = True
    ood_threshold: float = 0.0
    ood_soft_penalty: bool = False
    ood_penalty_per_unit: float = 0.0
    reference_schedule: Schedule | None = None
    reference_response: RawModelOutput | None = None
    provenance: Mapping[str, str] = MappingProxyType({})

    @property
    def has_reference(self) -> bool:
        return self.reference_schedule is not None and self.reference_response is not None


__all__ = [
    "SearchEnvironment",
]
