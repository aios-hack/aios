from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable, MutableMapping, Sequence

import torch
from torch import Tensor

from backend.contexts.surrogate.application.validation import _validate
from backend.contexts.surrogate.domain.errors import SurrogateModelError
from backend.contexts.surrogate.domain.losses import (
    _elementwise_loss,
    _money_weights,
    _pairwise_ranking_loss,
    _proxy_value,
    _scenario_money,
    _spearman,
)
from backend.contexts.surrogate.domain.model_choices import (
    _LOSSES,
    _LR_SCHEDULES,
    _SCENARIO_CONTEXTS,
    _SELECTION_CRITERIA,
)
from backend.contexts.surrogate.domain.model_types import (
    EpochMetrics,
    TARGET_NAMES,
    TrainingResult,
    _NUMERIC_NAMES,
)

if TYPE_CHECKING:
    from backend.contexts.surrogate.application.model import TrajectorySurrogate


def fit_tensors(
    model: "TrajectorySurrogate",
    *,
    train: tuple[Tensor, Tensor, Tensor],
    validation: tuple[Tensor, Tensor, Tensor],
    validation_node_counts: Sequence[int],
    train_node_counts: Sequence[int] | None = None,
    dataset_hash: str,
    device: str | None = None,
    epoch_callback: Callable[[EpochMetrics], None] | None = None,
    target_stats: MutableMapping[str, int] | None = None,
    train_npv_rub: Tensor | None = None,
    validation_npv_rub: Tensor | None = None,
    batches: type,
    scenario_batches: type,
) -> TrainingResult:
    settings = model.config
    target_stats = {} if target_stats is None else target_stats
    selected_device = torch.device(
        device or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    network = model.network.to(selected_device)
    train_x, train_wells, train_y = train
    val_x, val_wells, val_y = validation
    validation_scenarios = len(validation_node_counts)

    generator = torch.Generator().manual_seed(settings.seed)
    ranking = settings.ranking_loss_weight > 0.0
    if (train_npv_rub is None) != (validation_npv_rub is None):
        raise SurrogateModelError("exact ranking targets are required for both train and validation")
    for name, values, counts in (
        ("train", train_npv_rub, train_node_counts),
        ("validation", validation_npv_rub, validation_node_counts),
    ):
        if values is not None and (
            counts is None or values.shape != (len(counts),)
            or not bool(torch.isfinite(values).all())
        ):
            raise SurrogateModelError(f"{name}: wrong axis or a non-numeric NPV label")
    if ranking and not settings.money_rub_per_unit:
        raise SurrogateModelError("the ranking loss requires money coefficients")
    if ranking and not train_node_counts:
        raise SurrogateModelError(
            "ranking_loss_weight requires train_node_counts: without a split by "
            "scenario no pairwise comparison can be assembled"
        )
    if ranking:
        step_column = len(_NUMERIC_NAMES) + len(model.static_feature_names)
        size = train_node_counts[0]
        if any(count <= 0 for count in train_node_counts) or sum(train_node_counts) != len(train_x) or len(set(train_node_counts)) != 1:
            raise SurrogateModelError("ranking training requires identical full scenario axes")
        for start in range(size, len(train_x), size):
            if (
                not torch.equal(train_wells[start:start + size], train_wells[:size])
                or not torch.equal(train_x[start:start + size, step_column], train_x[:size, step_column])
            ):
                raise SurrogateModelError("well/step order diverged between the scenarios of the ranking batch")
    train_loader = (
        scenario_batches(
            (train_x, train_wells, train_y),
            train_node_counts,
            scenarios_per_batch=settings.ranking_scenarios_per_batch,
            nodes_per_scenario=settings.ranking_nodes_per_scenario,
            generator=generator,
            scenario_targets=train_npv_rub,
        )
        if ranking
        else batches(
            (train_x, train_wells, train_y),
            batch_size=settings.batch_size,
            generator=generator,
        )
    )
    validation_loader = batches(
        (val_x, val_wells, val_y), batch_size=settings.batch_size
    )
    optimizer = torch.optim.AdamW(
        network.parameters(),
        lr=settings.learning_rate,
        weight_decay=settings.weight_decay,
    )
    scheduler = (
        torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=settings.max_epochs
        )
        if settings.lr_schedule == "cosine"
        else None
    )

    weighted = bool(settings.money_rub_per_unit)
    target_scale = torch.tensor(
        model.target_scaler.scale, dtype=train_y.dtype, device=selected_device
    )
    target_mean = torch.tensor(
        model.target_scaler.mean, dtype=train_y.dtype, device=selected_device
    )
    rub_per_unit = torch.tensor(
        settings.money_rub_per_unit or (0.0,) * len(TARGET_NAMES),
        dtype=train_y.dtype,
        device=selected_device,
    )
    scenario_index = torch.repeat_interleave(
        torch.arange(validation_scenarios),
        torch.tensor(list(validation_node_counts)),
    )
    criterion = settings.select_by if weighted else "loss"

    best_loss = math.inf
    best_state: dict[str, Tensor] | None = None
    best_epoch = 0
    stale = 0
    history: list[EpochMetrics] = []
    for epoch in range(1, settings.max_epochs + 1):
        network.train()
        total = 0.0
        count = 0
        for batch in train_loader:
            if ranking:
                x, well_index, y, groups, n_groups = batch[:5]
                groups = groups.to(selected_device)
            else:
                x, well_index, y = batch
            x = x.to(selected_device)
            well_index = well_index.to(selected_device)
            y = y.to(selected_device)
            optimizer.zero_grad(set_to_none=True)
            prediction = network(x, well_index)
            if weighted:
                elementwise = _elementwise_loss(prediction, y, settings)
                weights = _money_weights(
                    y,
                    scale=target_scale,
                    mean=target_mean,
                    rub_per_unit=rub_per_unit,
                    alpha=settings.money_weight_alpha,
                    cap=settings.money_weight_cap,
                    parameterization=settings.target_parameterization,
                    oil_density_t_per_m3=settings.oil_density_t_per_m3,
                )
                loss = (elementwise * weights).mean()
            else:
                loss = _elementwise_loss(prediction, y, settings).mean()
            if ranking:
                money = torch.zeros(
                    n_groups, dtype=prediction.dtype, device=prediction.device
                )
                truth = torch.zeros_like(money)
                money.index_add_(0, groups, _proxy_value(
                    prediction, target_scale, target_mean, rub_per_unit,
                    settings))
                truth.index_add_(0, groups, _proxy_value(
                    y, target_scale, target_mean, rub_per_unit, settings))
                if train_npv_rub is not None:
                    truth = batch[5].to(device=selected_device, dtype=prediction.dtype)
                loss = loss + settings.ranking_loss_weight * (
                    _pairwise_ranking_loss(
                        money, truth,
                        top_weighted=settings.ranking_top_weighted,
                    )
                )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), max_norm=5.0)
            optimizer.step()
            total += float(loss.item()) * y.numel()
            count += y.numel()
        train_loss = total / max(1, count)
        outcome = _validate(
            network,
            validation_loader,
            selected_device,
            scale=target_scale if weighted else None,
            mean=target_mean if weighted else None,
            rub_per_unit=rub_per_unit if weighted else None,
            alpha=settings.money_weight_alpha,
            cap=settings.money_weight_cap,
            scenario_index=scenario_index if criterion == "rank" else None,
            scenario_count=validation_scenarios if criterion == "rank" else 0,
            parameterization=settings.target_parameterization,
            oil_density_t_per_m3=settings.oil_density_t_per_m3,
            settings=settings,
            scenario_targets=validation_npv_rub,
        )
        validation_loss = outcome.loss
        current_lr = float(optimizer.param_groups[0]["lr"])
        if scheduler is not None:
            scheduler.step()
        if criterion == "rank":
            score = -outcome.rank
        elif criterion == "money":
            score = outcome.money_loss
        else:
            score = validation_loss
        epoch_metrics = EpochMetrics(
            epoch,
            train_loss,
            validation_loss,
            validation_money_loss=outcome.money_loss,
            validation_rank=outcome.rank,
            learning_rate=current_lr,
        )
        history.append(epoch_metrics)
        if epoch_callback is not None:
            epoch_callback(epoch_metrics)
        if score < best_loss - 1e-6:
            best_loss = score
            best_epoch = epoch
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in network.state_dict().items()
            }
            stale = 0
        else:
            stale += 1
            if stale >= settings.patience:
                break
    if best_state is None:
        raise SurrogateModelError("training did not produce a finite validation loss")
    network.load_state_dict(best_state)
    model.network = network.cpu().eval()
    model.version = model._fingerprint()
    return TrainingResult(
        model=model,
        history=tuple(history),
        best_epoch=best_epoch,
        dataset_hash=dataset_hash,
        backflow_intervals=target_stats.get("backflow_intervals", 0),
        backflow_worst_tonnes=target_stats.get("backflow_worst_milli", 0) / 1000.0,
        target_rows=target_stats.get("target_rows", 0),
    )


__all__ = [
    "fit_tensors",
]
