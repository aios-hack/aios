from __future__ import annotations

from backend.contexts.surrogate.domain.model_types import (
    ModelConfig,
)
from backend.contexts.surrogate.domain.losses import (
    _elementwise_loss,
    _money_weights,
    _scenario_money,
    _spearman,
)
from backend.contexts.surrogate.domain.network import (
    _NodeNetwork,
)
from dataclasses import (
    dataclass,
)
import torch
from torch import (
    Tensor,
)


@dataclass(frozen=True, slots=True)
class _ValidationOutcome:
    loss: float
    money_loss: float
    rank: float


def _validate(
    network: _NodeNetwork,
    loader: "_Batches | DataLoader",
    device: torch.device,
    *,
    scale: Tensor | None = None,
    mean: Tensor | None = None,
    rub_per_unit: Tensor | None = None,
    alpha: float = 0.0,
    cap: float = 1.0,
    scenario_index: Tensor | None = None,
    scenario_count: int = 0,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
    settings: "ModelConfig | None" = None,
    scenario_targets: Tensor | None = None,
) -> _ValidationOutcome:
    network.eval()
    settings = settings or ModelConfig()
    total = 0.0
    money_total = 0.0
    count = 0
    weighted = rub_per_unit is not None and scale is not None and mean is not None
    ranked = weighted and scenario_index is not None and scenario_count > 0
    predicted_chunks: list[Tensor] = []
    actual_chunks: list[Tensor] = []
    with torch.no_grad():
        for x, well_index, y in loader:
            x = x.to(device)
            well_index = well_index.to(device)
            y = y.to(device)
            prediction = network(x, well_index)
            elementwise = _elementwise_loss(prediction, y, settings)
            total += float(elementwise.sum().item())
            if weighted:
                weights = _money_weights(
                    y, scale=scale, mean=mean, rub_per_unit=rub_per_unit,
                    alpha=alpha, cap=cap, parameterization=parameterization,
                    oil_density_t_per_m3=oil_density_t_per_m3,
                )
                money_total += float((elementwise * weights).sum().item())
            if ranked:
                predicted_chunks.append(prediction.cpu())
                actual_chunks.append(y.cpu())
            count += y.numel()
    divisor = max(1, count)
    loss = total / divisor
    money_loss = money_total / divisor if weighted else loss
    rank = 0.0
    if ranked:
        cpu_scale = scale.cpu()
        cpu_mean = mean.cpu()
        cpu_rub = rub_per_unit.cpu()
        predicted_money = _scenario_money(
            torch.cat(predicted_chunks), scenario_index, scenario_count,
            scale=cpu_scale, mean=cpu_mean, rub_per_unit=cpu_rub,
            parameterization=parameterization,
            oil_density_t_per_m3=oil_density_t_per_m3,
        )
        actual_money = _scenario_money(
            torch.cat(actual_chunks), scenario_index, scenario_count,
            scale=cpu_scale, mean=cpu_mean, rub_per_unit=cpu_rub,
            parameterization=parameterization,
            oil_density_t_per_m3=oil_density_t_per_m3,
        )
        rank = _spearman(
            predicted_money,
            actual_money if scenario_targets is None else scenario_targets.to(predicted_money),
        )
    return _ValidationOutcome(loss=loss, money_loss=money_loss, rank=rank)


def _loss_on_loader(
    network: _NodeNetwork,
    loader: "_Batches | DataLoader",
    device: torch.device,
) -> float:
    return _validate(network, loader, device).loss


__all__ = [
    "_ValidationOutcome",
    "_loss_on_loader",
    "_validate",
]
