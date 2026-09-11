from __future__ import annotations

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.schedule.domain.schedule import (
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
)
from backend.contexts.surrogate.domain.errors import PhysicsCheckError
from backend.contexts.surrogate.domain.physics_checks.combined import check_physics
from backend.contexts.surrogate.domain.physics_checks.pairwise import (
    check_pair,
    injection_only_pair,
    lambda_column_sums,
)
from backend.contexts.surrogate.domain.physics_checks.single import check_prediction
from backend.contexts.surrogate.domain.physics_checks.types import (
    BhpLimits,
    DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
    DEFAULT_OIL_DENSITY_T_PER_M3,
    DEFAULT_RELATIVE_TOLERANCE,
    DEFAULT_WATERCUT_TOLERANCE,
    DEFAULT_ZERO_TOLERANCE,
    FORMAT,
    Invariant,
    PhysicsFlag,
    PhysicsReport,
    Severity,
    severity_of,
)
from backend.contexts.surrogate.domain.raw_model_output import (
    RawModelOutput,
    RawWellStepPrediction,
)


__all__ = [
    "BhpLimits",
    "DEFAULT_MAX_EXAMPLES_PER_INVARIANT",
    "DEFAULT_OIL_DENSITY_T_PER_M3",
    "DEFAULT_RELATIVE_TOLERANCE",
    "DEFAULT_WATERCUT_TOLERANCE",
    "DEFAULT_ZERO_TOLERANCE",
    "FORMAT",
    "Invariant",
    "PhysicsCheckError",
    "PhysicsFlag",
    "PhysicsReport",
    "Severity",
    "check_pair",
    "check_physics",
    "check_prediction",
    "injection_only_pair",
    "lambda_column_sums",
    "severity_of",
]
