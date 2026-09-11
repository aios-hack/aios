from __future__ import annotations

from backend.contexts.surrogate.domain.model_types import (
    ModelConfig,
    TARGET_NAMES,
    _NUMERIC_NAMES,
)

import math
from typing import (
    Sequence,
)
import torch
from torch import Tensor, nn
from backend.core.contracts import (
    Availability,
    N_INTERVALS,
    OperatingStatus,
    Role,
)
from backend.contexts.surrogate.domain.features import (
    WellStepFeatures,
)


class _NodeNetwork(nn.Module):
    def __init__(
        self,
        numeric_width: int,
        n_wells: int,
        config: ModelConfig,
    ) -> None:
        super().__init__()
        self.well_embedding = nn.Embedding(n_wells, config.well_embedding_dim)
        width = numeric_width + config.well_embedding_dim
        self.residual = config.residual
        if self.residual:
            # Остаточные блоки одинаковой ширины: градиент доходит до первых
            # слоёв без затухания, поэтому глубина перестаёт мешать обучению.
            self.stem = nn.Linear(width, config.hidden_width)
            self.blocks = nn.ModuleList(
                nn.Sequential(
                    nn.LayerNorm(config.hidden_width),
                    nn.Linear(config.hidden_width, config.hidden_width),
                    nn.SiLU(),
                    nn.Dropout(config.dropout),
                    nn.Linear(config.hidden_width, config.hidden_width),
                )
                for _ in range(config.hidden_layers)
            )
            self.head = nn.Sequential(
                nn.LayerNorm(config.hidden_width),
                nn.Linear(config.hidden_width, len(TARGET_NAMES)),
            )
            self.body = None
            return
        layers: list[nn.Module] = []
        for _ in range(config.hidden_layers):
            layers.extend(
                (
                    nn.Linear(width, config.hidden_width),
                    nn.SiLU(),
                    nn.LayerNorm(config.hidden_width),
                    nn.Dropout(config.dropout),
                )
            )
            width = config.hidden_width
        layers.append(nn.Linear(width, len(TARGET_NAMES)))
        self.body = nn.Sequential(*layers)

    def forward(self, numeric: Tensor, well_index: Tensor) -> Tensor:
        embedded = self.well_embedding(well_index)
        features = torch.cat((numeric, embedded), dim=1)
        if not self.residual:
            return self.body(features)
        hidden = self.stem(features)
        for block in self.blocks:
            hidden = hidden + block(hidden)
        return self.head(hidden)


def _one_hot(value: object, members: Sequence[object]) -> list[float]:
    return [1.0 if value is member else 0.0 for member in members]


def _node_vector(node: WellStepFeatures) -> list[float]:
    numeric = [math.log1p(float(getattr(node, name))) for name in _NUMERIC_NAMES]
    static = [float(value) for value in node.static_values]
    fraction = node.control_step / max(1, N_INTERVALS - 1)
    phase = 2.0 * math.pi * fraction
    return [
        *numeric,
        *static,
        fraction,
        math.sin(phase),
        math.cos(phase),
        *_one_hot(node.availability, tuple(Availability)),
        *_one_hot(node.role, tuple(Role)),
        *_one_hot(node.operating_status, tuple(OperatingStatus)),
    ]
