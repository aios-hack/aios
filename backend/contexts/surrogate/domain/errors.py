from __future__ import annotations

from backend.shared.errors import (
    DomainError,
    ValidationError,
)


class SurrogateModelError(DomainError):
    default_code = "surrogate.model"


class FeatureError(DomainError):
    default_code = "surrogate.features"


class MetricsError(DomainError):
    default_code = "surrogate.metrics"


class CrmError(DomainError):
    default_code = "surrogate.crm"


class PhysicsCheckError(DomainError):
    default_code = "surrogate.physics"


class ScenarioNpvHeadError(DomainError):
    default_code = "surrogate.npv_head"


class BlockNpvHeadError(DomainError):
    default_code = "surrogate.npv_block_head"


class NpvCalibrationError(DomainError):
    default_code = "surrogate.npv_calibration"


class AdapterError(DomainError):
    default_code = "surrogate.adapter"


class TrajectoryEnsembleError(DomainError):
    default_code = "surrogate.ensemble"


class CycleError(DomainError):
    default_code = "surrogate.pipeline"


class TrainingCommandError(ValidationError):
    default_code = "surrogate.training"


class ModelZContextError(ValidationError):
    default_code = "surrogate.model_z_context"


__all__ = [
    "AdapterError",
    "BlockNpvHeadError",
    "CrmError",
    "CycleError",
    "FeatureError",
    "MetricsError",
    "ModelZContextError",
    "NpvCalibrationError",
    "PhysicsCheckError",
    "ScenarioNpvHeadError",
    "SurrogateModelError",
    "TrainingCommandError",
    "TrajectoryEnsembleError",
]
