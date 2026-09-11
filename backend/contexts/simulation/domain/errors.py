from __future__ import annotations

from backend.shared.errors import (
    InfrastructureError,
    ValidationError,
)


class OpmRunnerError(InfrastructureError):
    default_code = "simulation.runner"


class DatasetError(ValidationError):
    default_code = "simulation.dataset"


class DatasetPlanError(ValidationError):
    default_code = "simulation.perturbation_design"


class ResponseLoaderError(ValidationError):
    default_code = "simulation.response"


class SubmissionTractError(ValidationError):
    default_code = "simulation.submission_tract"


__all__ = [
    "DatasetError",
    "DatasetPlanError",
    "OpmRunnerError",
    "ResponseLoaderError",
    "SubmissionTractError",
]
