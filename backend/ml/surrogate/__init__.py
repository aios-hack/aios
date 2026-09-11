"""Schedule-only features for the reservoir surrogate."""

from backend.contexts.surrogate.application.adapter import AdapterError, ResponseAdapter
from backend.contexts.surrogate.domain.features import (
    FeatureContext,
    FeatureError,
    HistoryTargets,
    LambdaEdgeFeature,
    ScheduleFeatureizer,
    SurrogateInput,
    WellStepFeatures,
    history_targets_from_deck,
)
from backend.contexts.surrogate.domain.raw_model_output import (
    RawModelOutput,
    RawWellStepPrediction,
)

__all__ = [
    "AdapterError",
    "FeatureContext",
    "FeatureError",
    "HistoryTargets",
    "LambdaEdgeFeature",
    "RawModelOutput",
    "RawWellStepPrediction",
    "ResponseAdapter",
    "ScheduleFeatureizer",
    "SurrogateInput",
    "WellStepFeatures",
    "history_targets_from_deck",
]
