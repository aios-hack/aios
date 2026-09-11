from __future__ import annotations

from backend.contexts.surrogate.domain.physics_checks import (
    BhpLimits,
    DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
    DEFAULT_OIL_DENSITY_T_PER_M3,
    DEFAULT_RELATIVE_TOLERANCE,
    DEFAULT_WATERCUT_TOLERANCE,
    DEFAULT_ZERO_TOLERANCE,
    FORMAT,
    Invariant,
    PhysicsCheckError,
    PhysicsFlag,
    PhysicsReport,
    Severity,
    check_pair,
    check_physics,
    check_prediction,
    injection_only_pair,
    lambda_column_sums,
    severity_of,
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
