from __future__ import annotations

from typing import Mapping, Sequence

from backend.contexts.surrogate.domain.physics_checks import Invariant

from backend.shared.errors import (
    DomainError,
    ValidationError,
)


class OptimizerError(DomainError):
    default_code = "optimization.optimizer"


class ConvergenceError(DomainError):
    default_code = "optimization.convergence"


class ScheduleSearchError(DomainError):
    default_code = "optimization.environment"


class LambdaDesyncError(ScheduleSearchError):
    default_code = "optimization.lambda_desync"


class EnsembleSpreadError(ScheduleSearchError):
    default_code = "optimization.ensemble_spread"


class SearchRunError(DomainError):
    default_code = "optimization.search_run"


class BhpToleranceError(SearchRunError):
    default_code = "optimization.bhp_tolerance"


class OpmBudgetError(SearchRunError):
    default_code = "optimization.opm_budget"


class ConnectivitySearchError(SearchRunError):
    default_code = "optimization.connectivity"


class VerificationError(DomainError):
    default_code = "optimization.verification"


class VerificationGuardError(DomainError):
    default_code = "optimization.verification.guard"


class ComparisonError(DomainError):
    default_code = "optimization.comparison"


class ScenarioBaselineError(DomainError):
    default_code = "optimization.scenario_baseline"


class OpmActiveCalibrationError(DomainError):
    default_code = "optimization.opm_calibration"


class RuntimeArtifactError(ValidationError):
    default_code = "optimization.artifact"


_DIFFERENTIAL_INVARIANT_NAMES: tuple[str, ...] = (
    Invariant.INJECTION_RESPONSE.value,
    Invariant.MATERIAL_BALANCE.value,
)

class OutOfDomainScheduleError(ScheduleSearchError):
    default_code = "optimization.out_of_domain"

    def __init__(
        self,
        score: float,
        description: str,
        exceedances: Sequence[Mapping[str, object]] = (),
    ) -> None:
        self.score = float(score)
        self.description = description
        self.exceedances = tuple(dict(item) for item in exceedances)
        super().__init__(
            f"candidate is outside the training domain: ood_score={score:.6g}; {description}"
        )


class PhysicallyImpossibleScheduleError(ScheduleSearchError):
    default_code = "optimization.physically_impossible"

    def __init__(
        self,
        counts: Mapping[str, int],
        description: str,
        missing_invariants: Sequence[str] = (),
    ) -> None:
        self.counts = dict(counts)
        self.description = description
        self.missing_invariants = tuple(missing_invariants)
        super().__init__(f"candidate is physically impossible: {description}")


class MissingReferenceError(PhysicallyImpossibleScheduleError):
    default_code = "optimization.missing_reference"

    SELF_REFERENCE = (
        "the reference and the candidate are the same schedule: differential "
        "invariants compare the candidate against the reference, and when they "
        "coincide every difference is identically zero, so the invariant asserts "
        "nothing; it is not violated, it is undefined"
    )

    def __init__(self, reason: str) -> None:
        description = (
            "the reference is unavailable, differential invariants were not checked: "
            f"{', '.join(_DIFFERENTIAL_INVARIANT_NAMES)}; {reason}"
        )
        super().__init__({}, description, _DIFFERENTIAL_INVARIANT_NAMES)


SELF_REFERENCE_SKIP_REASON = MissingReferenceError.SELF_REFERENCE


__all__ = [
    "SELF_REFERENCE_SKIP_REASON",
    "PhysicallyImpossibleScheduleError",
    "OutOfDomainScheduleError",
    "MissingReferenceError",
    "BhpToleranceError",
    "ComparisonError",
    "ConnectivitySearchError",
    "ConvergenceError",
    "EnsembleSpreadError",
    "LambdaDesyncError",
    "OpmActiveCalibrationError",
    "OpmBudgetError",
    "OptimizerError",
    "RuntimeArtifactError",
    "ScenarioBaselineError",
    "ScheduleSearchError",
    "SearchRunError",
    "VerificationError",
    "VerificationGuardError",
]
