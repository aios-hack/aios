from __future__ import annotations

from backend.contexts.surrogate.domain.model_types import (
    TrainingExample,
    _BACKFLOW_FIELDS,
    _BACKFLOW_FLOOR,
    _BACKFLOW_SHARE_LIMIT,
    _ROUNDOFF_TOLERANCE,
)

from backend.contexts.surrogate.domain.network import (
    _node_vector,
)
from backend.contexts.surrogate.domain.errors import (
    SurrogateModelError,
)
import math
from typing import (
    Mapping,
    MutableMapping,
    Sequence,
)
import torch
from torch import (
    Tensor,
)
from backend.contexts.schedule.domain.schedule import N_INTERVALS, Role
from backend.contexts.surrogate.domain.features import (
    SurrogateInput,
)


def _validate_input(item: SurrogateInput) -> None:
    expected = {(well, step) for well in item.wells for step in range(N_INTERVALS)}
    actual = {(node.well, node.control_step) for node in item.nodes}
    if actual != expected or len(item.nodes) != len(expected):
        raise SurrogateModelError("SurrogateInput does not cover wells × 224 without duplicates")
    if any(len(node.static_values) != len(item.static_feature_names) for node in item.nodes):
        raise SurrogateModelError("static_values does not match static_feature_names")


def _scenario_summary(x: Tensor, item: SurrogateInput, *, mode: object) -> Tensor:
    rows = x.shape[0]
    blocks = [x.mean(dim=0, keepdim=True)]
    if mode == "rich":
        blocks.extend((x.std(dim=0, keepdim=True), x.amax(dim=0, keepdim=True)))
        role_index = {role: index for index, role in enumerate(Role)}
        for role in (Role.PROD, Role.INJ):
            mask = torch.tensor(
                [node.role is role for node in item.nodes], dtype=torch.bool
            )
            blocks.append(
                x[mask].mean(dim=0, keepdim=True)
                if bool(mask.any())
                else torch.zeros(1, x.shape[1], dtype=x.dtype)
            )
    summary = torch.cat(blocks, dim=1)
    return torch.nan_to_num(summary).expand(rows, -1)


def build_features(
    item: SurrogateInput,
    wells: tuple[str, ...],
    *,
    scenario_context: object = False,
) -> tuple[Tensor, Tensor]:
    _validate_input(item)
    if item.wells != wells:
        raise SurrogateModelError(f"the wells axis diverged: {item.wells} != {wells}")
    well_to_index = {well: index for index, well in enumerate(wells)}
    x = torch.tensor([_node_vector(node) for node in item.nodes], dtype=torch.float32)
    if scenario_context:
        x = torch.cat((x, _scenario_summary(x, item, mode=scenario_context)), dim=1)
    well_index = torch.tensor(
        [well_to_index[node.well] for node in item.nodes], dtype=torch.long
    )
    return x, well_index


def _watercut_row(
    raw: Mapping[str, float], *, oil_density_t_per_m3: float
) -> list[float]:
    liquid = raw["liquid_volume_delta"]
    if liquid > 0.0:
        oil_volume = raw["oil_mass_delta"] / oil_density_t_per_m3
        watercut = 1.0 - oil_volume / liquid
    else:
        watercut = 0.0
    return [
        liquid,
        watercut,
        raw["injection_volume_delta"],
        raw["liquid_rate"],
        raw["injection_rate"],
        raw["bhp"],
    ]


def _targets(
    example: TrainingExample,
    stats: MutableMapping[str, int] | None = None,
    *,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
) -> Tensor:
    from backend.contexts.reservoir.domain.horizon import HORIZON
    item = example.input
    interval = {
        (row.well, row.control_step): row for row in example.response.interval_response
    }
    states = {
        (row.well, row.deck_date_index): row for row in example.response.state_at_date
    }
    rows: list[list[float]] = []
    for node in item.nodes:
        try:
            response = interval[(node.well, node.control_step)]
            state = states[(node.well, HORIZON.history_offset + 1 + node.control_step)]
        except KeyError as error:
            raise SurrogateModelError(
                f"the response does not cover ({node.well!r}, {node.control_step})"
            ) from error
        raw = {
            "oil_mass_delta": response.oil_mass_delta,
            "liquid_volume_delta": response.liquid_volume_delta,
            "injection_volume_delta": response.injection_volume_delta,
            "liquid_rate": state.liquid_rate,
            "injection_rate": state.injection_rate,
            "bhp": state.bhp,
        }
        for name, value in raw.items():
            if not math.isfinite(value):
                raise SurrogateModelError(
                    f"non-numeric target ({node.well!r}, {node.control_step}) "
                    f"{name}={value!r}"
                )
            if value >= -_ROUNDOFF_TOLERANCE:
                continue
            if name not in _BACKFLOW_FIELDS or value < _BACKFLOW_FLOOR:
                raise SurrogateModelError(
                    f"negative target ({node.well!r}, {node.control_step}) "
                    f"{name}={value!r}"
                )
            if stats is not None:
                stats["backflow_intervals"] = stats.get("backflow_intervals", 0) + 1
                stats["backflow_worst_milli"] = min(
                    stats.get("backflow_worst_milli", 0), int(value * 1000)
                )
        values = (
            _watercut_row(raw, oil_density_t_per_m3=oil_density_t_per_m3)
            if parameterization == "watercut"
            else list(raw.values())
        )
        rows.append([math.log1p(max(0.0, float(value))) for value in values])
    return torch.tensor(rows, dtype=torch.float32)


def _example_tensors(
    examples: Sequence[TrainingExample],
    wells: tuple[str, ...],
    stats: MutableMapping[str, int] | None = None,
    *,
    parameterization: str = "absolute",
    oil_density_t_per_m3: float = 0.9131,
    scenario_context: bool = False,
) -> tuple[Tensor, Tensor, Tensor]:
    xs: list[Tensor] = []
    indices: list[Tensor] = []
    ys: list[Tensor] = []
    counters: dict[str, int] = {}
    for example in examples:
        x, well_index = build_features(
            example.input, wells, scenario_context=scenario_context
        )
        xs.append(x)
        indices.append(well_index)
        ys.append(
            _targets(
                example,
                counters,
                parameterization=parameterization,
                oil_density_t_per_m3=oil_density_t_per_m3,
            )
        )
    if not xs:
        raise SurrogateModelError("the training sample is empty")
    target = torch.cat(ys)
    backflow = counters.get("backflow_intervals", 0)
    share = backflow / max(1, target.shape[0])
    if share > _BACKFLOW_SHARE_LIMIT:
        raise SurrogateModelError(
            f"{backflow} backflows out of {target.shape[0]} intervals ({share:.3%}), "
            f"above the {_BACKFLOW_SHARE_LIMIT:.1%} threshold; this is no longer backflow "
            "but a discrepancy in the response parsing"
        )
    if stats is not None:
        stats.update(counters)
        stats["target_rows"] = int(target.shape[0])
    return torch.cat(xs), torch.cat(indices), target
