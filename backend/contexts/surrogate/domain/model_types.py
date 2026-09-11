from __future__ import annotations

from backend.contexts.surrogate.domain.model_choices import (
    TARGET_PARAMETERIZATIONS,
    _LOSSES,
    _LR_SCHEDULES,
    _SCENARIO_CONTEXTS,
    _SELECTION_CRITERIA,
)


from backend.contexts.surrogate.domain.errors import (
    SurrogateModelError,
)
import math
from dataclasses import (
    dataclass,
)
import torch
from torch import (
    Tensor,
)
from backend.core.contracts import (
    ResponseArtifact,
)
from backend.contexts.surrogate.domain.features import (
    SurrogateInput,
)


TARGET_NAMES: tuple[str, ...] = (
    "oil_mass_delta",
    "liquid_volume_delta",
    "injection_volume_delta",
    "liquid_rate",
    "injection_rate",
    "bhp",
)


_WATERCUT_CEILING = 1.0


_ROUNDOFF_TOLERANCE = 1e-3


_BACKFLOW_FIELDS = frozenset({"oil_mass_delta"})


_BACKFLOW_FLOOR = -1e3


_BACKFLOW_SHARE_LIMIT = 0.01


_NUMERIC_NAMES: tuple[str, ...] = (
    "setpoint_m3_per_day",
    "effective_target_rate_m3_per_day",
    "cumulative_target_liquid_m3",
    "cumulative_target_injection_m3",
    "cumulative_neighbor_injection_m3",
    "current_neighbor_injection_m3_per_day",
    "event_count",
    "fixed_event_count",
)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    hidden_width: int = 128
    hidden_layers: int = 3
    well_embedding_dim: int = 16
    dropout: float = 0.05
    learning_rate: float = 2e-3
    weight_decay: float = 1e-5
    batch_size: int = 32_768
    max_epochs: int = 80
    patience: int = 10
    seed: int = 20260816
    money_rub_per_unit: tuple[float, ...] = ()
    money_weight_alpha: float = 0.7
    money_weight_cap: float = 50.0
    lr_schedule: str = "none"
    select_by: str = "loss"
    target_parameterization: str = "absolute"
    oil_density_t_per_m3: float = 0.9131
    loss: str = "smooth_l1"
    huber_delta: float = 0.1
    residual: bool = False
    scenario_context: object = False
    ranking_loss_weight: float = 0.0
    ranking_top_weighted: bool = False
    ranking_scenarios_per_batch: int = 48
    ranking_nodes_per_scenario: int = 4096

    def __post_init__(self) -> None:
        if self.hidden_width < 1 or self.hidden_layers < 1:
            raise SurrogateModelError("hidden_width/hidden_layers должны быть положительными")
        if self.well_embedding_dim < 1:
            raise SurrogateModelError("well_embedding_dim должен быть положительным")
        if not (0.0 <= self.dropout < 1.0):
            raise SurrogateModelError("dropout должен лежать в [0, 1)")
        if self.learning_rate <= 0.0 or self.weight_decay < 0.0:
            raise SurrogateModelError("learning_rate/weight_decay заданы неверно")
        if self.batch_size < 1 or self.max_epochs < 1 or self.patience < 1:
            raise SurrogateModelError("batch_size/max_epochs/patience должны быть положительными")
        object.__setattr__(self, "money_rub_per_unit", tuple(self.money_rub_per_unit))
        if self.money_rub_per_unit and len(self.money_rub_per_unit) != len(TARGET_NAMES):
            raise SurrogateModelError(
                f"money_rub_per_unit должен покрывать все {len(TARGET_NAMES)} целей"
            )
        if any(not math.isfinite(value) for value in self.money_rub_per_unit):
            raise SurrogateModelError("money_rub_per_unit содержит нечисловой коэффициент")
        if not 0.0 <= self.money_weight_alpha <= 1.0:
            raise SurrogateModelError("money_weight_alpha должен лежать в [0, 1]")
        if self.money_weight_cap < 1.0:
            raise SurrogateModelError("money_weight_cap должен быть не меньше 1")
        if self.lr_schedule not in _LR_SCHEDULES:
            raise SurrogateModelError(f"lr_schedule: {' или '.join(_LR_SCHEDULES)}")
        if self.select_by not in _SELECTION_CRITERIA:
            raise SurrogateModelError(f"select_by: {', '.join(_SELECTION_CRITERIA)}")
        if self.target_parameterization not in TARGET_PARAMETERIZATIONS:
            raise SurrogateModelError(
                f"target_parameterization: {' или '.join(TARGET_PARAMETERIZATIONS)}"
            )
        if not self.oil_density_t_per_m3 > 0.0:
            raise SurrogateModelError("oil_density_t_per_m3 должна быть положительной")
        if self.loss not in _LOSSES:
            raise SurrogateModelError(f"loss: {', '.join(_LOSSES)}")
        if self.scenario_context not in _SCENARIO_CONTEXTS:
            raise SurrogateModelError(
                "scenario_context: False, True, 'mean' или 'rich'"
            )
        if self.ranking_loss_weight < 0.0:
            raise SurrogateModelError("ranking_loss_weight не может быть отрицательным")
        if self.ranking_scenarios_per_batch < 2:
            raise SurrogateModelError(
                "ranking_scenarios_per_batch должен быть не меньше двух: "
                "попарное сравнение требует пары"
            )
        if self.ranking_nodes_per_scenario < 1:
            raise SurrogateModelError(
                "ranking_nodes_per_scenario должен быть положительным"
            )
        if not self.huber_delta > 0.0:
            raise SurrogateModelError("huber_delta должна быть положительной")


@dataclass(frozen=True, slots=True)
class Standardizer:
    mean: tuple[float, ...]
    scale: tuple[float, ...]

    @classmethod
    def fit(cls, values: Tensor) -> "Standardizer":
        if values.ndim != 2 or values.shape[0] == 0:
            raise SurrogateModelError("standardizer требует непустую матрицу")
        mean = values.mean(dim=0)
        scale = values.std(dim=0, unbiased=False)
        scale = torch.where(scale > 1e-8, scale, torch.ones_like(scale))
        return cls(tuple(mean.tolist()), tuple(scale.tolist()))

    def transform(self, values: Tensor) -> Tensor:
        mean = torch.tensor(self.mean, dtype=values.dtype, device=values.device)
        scale = torch.tensor(self.scale, dtype=values.dtype, device=values.device)
        return (values - mean) / scale

    def inverse(self, values: Tensor) -> Tensor:
        mean = torch.tensor(self.mean, dtype=values.dtype, device=values.device)
        scale = torch.tensor(self.scale, dtype=values.dtype, device=values.device)
        return values * scale + mean


@dataclass(frozen=True, slots=True)
class TrainingExample:
    input: SurrogateInput
    response: ResponseArtifact


@dataclass(frozen=True, slots=True)
class EpochMetrics:
    epoch: int
    train_loss: float
    validation_loss: float
    validation_money_loss: float = 0.0
    validation_rank: float = 0.0
    learning_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: "TrajectorySurrogate"
    history: tuple[EpochMetrics, ...]
    best_epoch: int
    dataset_hash: str
    backflow_intervals: int = 0
    backflow_worst_tonnes: float = 0.0
    target_rows: int = 0


__all__ = [
    "EpochMetrics",
    "ModelConfig",
    "Standardizer",
    "TARGET_NAMES",
    "TrainingExample",
    "TrainingResult",
]
