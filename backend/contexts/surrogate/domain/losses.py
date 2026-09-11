from __future__ import annotations


from backend.contexts.surrogate.domain.model_types import (
    _WATERCUT_CEILING,
)

import torch
from torch import (
    Tensor,
)


def _elementwise_loss(
    prediction: Tensor, target: Tensor, settings: "ModelConfig"
) -> Tensor:
    if settings.loss == "mse":
        return (prediction - target) ** 2
    if settings.loss == "huber":
        return torch.nn.functional.huber_loss(
            prediction, target, reduction="none", delta=settings.huber_delta
        )
    return torch.nn.functional.smooth_l1_loss(prediction, target, reduction="none")


def _money_coefficients(
    physical: Tensor,
    *,
    rub_per_unit: Tensor,
    parameterization: str,
    oil_density_t_per_m3: float,
) -> Tensor:
    if parameterization != "watercut":
        return rub_per_unit
    liquid = physical[:, 0:1]
    watercut = physical[:, 1:2].clamp(min=0.0, max=_WATERCUT_CEILING)
    oil_margin = rub_per_unit[0]
    opex_liquid = rub_per_unit[1]
    opex_injection = rub_per_unit[2]
    zeros = torch.zeros_like(liquid)
    return torch.cat(
        (
            opex_liquid + (1.0 - watercut) * oil_density_t_per_m3 * oil_margin,
            -liquid * oil_density_t_per_m3 * oil_margin,
            opex_injection.expand_as(liquid),
            zeros,
            zeros,
            zeros,
        ),
        dim=1,
    )


def _money_weights(
    y: Tensor,
    *,
    scale: Tensor,
    mean: Tensor,
    rub_per_unit: Tensor,
    alpha: float,
    cap: float,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
) -> Tensor:
    physical = torch.expm1(y * scale + mean).clamp_min(0.0)
    coefficients = _money_coefficients(
        physical,
        rub_per_unit=rub_per_unit,
        parameterization=parameterization,
        oil_density_t_per_m3=oil_density_t_per_m3,
    )
    weight = coefficients.abs() * scale * torch.exp(y * scale + mean)
    average = weight.mean()
    if not bool(torch.isfinite(average)) or float(average) <= 0.0:
        return torch.ones_like(y)
    normalized = (weight / average).clamp(1.0 / cap, cap)
    return alpha * normalized + (1.0 - alpha)


def _ranks(values: Tensor) -> Tensor:
    order = torch.argsort(values)
    ranks = torch.empty_like(values)
    _, inverse, counts = torch.unique_consecutive(values[order], return_inverse=True, return_counts=True)
    average_positions = counts.cumsum(0).to(values.dtype) - (counts.to(values.dtype) + 1) / 2
    ranks[order] = average_positions[inverse]
    return ranks


def _spearman(left: Tensor, right: Tensor) -> float:
    if left.numel() < 2:
        return 0.0
    centred_left = _ranks(left) - (left.numel() - 1) / 2.0
    centred_right = _ranks(right) - (right.numel() - 1) / 2.0
    denominator = torch.sqrt(
        (centred_left * centred_left).sum() * (centred_right * centred_right).sum()
    )
    if float(denominator) == 0.0:
        return 0.0
    return float((centred_left * centred_right).sum() / denominator)


def _scenario_money(
    standardized: Tensor,
    scenario_index: Tensor,
    scenario_count: int,
    *,
    scale: Tensor,
    mean: Tensor,
    rub_per_unit: Tensor,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
) -> Tensor:
    physical = torch.expm1(standardized * scale + mean).clamp_min(0.0)
    if parameterization == "watercut":
        liquid = physical[:, 0]
        watercut = physical[:, 1].clamp(min=0.0, max=_WATERCUT_CEILING)
        oil = liquid * (1.0 - watercut) * oil_density_t_per_m3
        value = (
            oil * rub_per_unit[0]
            + liquid * rub_per_unit[1]
            + physical[:, 2] * rub_per_unit[2]
        )
    else:
        oil = torch.minimum(physical[:, 0], physical[:, 1] * oil_density_t_per_m3)
        value = oil * rub_per_unit[0] + (physical[:, 1:] * rub_per_unit[1:]).sum(dim=1)
    totals = torch.zeros(scenario_count, dtype=value.dtype, device=value.device)
    totals.index_add_(0, scenario_index, value)
    return totals


def _standardize_scores(values: Tensor) -> Tensor:
    centred = values - values.mean()
    scale = torch.sqrt((centred * centred).mean() + 1e-12)
    return centred / scale


def _proxy_value(
    standardized: Tensor,
    scale: Tensor,
    mean: Tensor,
    rub_per_unit: Tensor,
    settings: "ModelConfig",
) -> Tensor:
    physical = torch.expm1(standardized * scale + mean).clamp_min(0.0)
    if settings.target_parameterization == "watercut":
        liquid = physical[:, 0]
        watercut = physical[:, 1].clamp(min=0.0, max=_WATERCUT_CEILING)
        oil = liquid * (1.0 - watercut) * settings.oil_density_t_per_m3
        return (oil * rub_per_unit[0] + liquid * rub_per_unit[1]
                + physical[:, 2] * rub_per_unit[2])
    oil = torch.minimum(physical[:, 0], physical[:, 1] * settings.oil_density_t_per_m3)
    return oil * rub_per_unit[0] + (physical[:, 1:] * rub_per_unit[1:]).sum(dim=1)


def _pairwise_ranking_loss(
    predicted: Tensor, actual: Tensor, *, top_weighted: bool = False
) -> Tensor:
    predicted = _standardize_scores(predicted)
    difference = predicted.unsqueeze(0) - predicted.unsqueeze(1)
    truth = actual.unsqueeze(0) - actual.unsqueeze(1)
    mask = truth != 0
    if not bool(mask.any()):
        return predicted.sum() * 0.0
    penalty = torch.nn.functional.softplus(
        -difference[mask] * torch.sign(truth[mask])
    )
    if not top_weighted:
        return penalty.mean()
    order = torch.argsort(actual, descending=True)
    position = torch.empty_like(actual)
    position[order] = torch.arange(
        actual.numel(), dtype=actual.dtype, device=actual.device
    )
    gain = 1.0 / (1.0 + position)
    weight = (gain.unsqueeze(0) - gain.unsqueeze(1)).abs()[mask]
    total = weight.sum()
    if float(total) <= 0.0:
        return penalty.mean()
    return (penalty * weight).sum() / total


