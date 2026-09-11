
from __future__ import annotations

import hashlib
from typing import Literal

import torch
from torch import Tensor

from backend.contexts.schedule.domain.schedule import N_INTERVALS

from backend.contexts.surrogate.domain.npv_head import ScenarioNpvHeadError

FORMAT = "aios.surrogate-scenario-npv-head.v1"
BASE_FEATURES = 21
TEMPORAL_BINS = 28
WELL_TEMPORAL_FEATURES = 6
ECONOMIC_WELL_FEATURES = 14
ECONOMIC_AGGREGATIONS = 4
KernelName = Literal["linear", "poly2", "rbf"]
FeatureSet = Literal["global", "temporal", "full", "economic", "well_temporal"]
FEATURE_PROVENANCE_FILES = (
    "backend/contexts/schedule/domain/schedule.py",
    "backend/contexts/surrogate/domain/features/featureizer.py",
    "backend/contexts/surrogate/domain/network.py",
    "backend/contexts/surrogate/domain/npv_economic_features.py",
)

LEGACY_FEATURE_PROVENANCE_HASHES = {
    "0071d65d57e16ada366585177aadd2235074022d094cc156ab72b00b22d6ad7c",
}


def feature_implementation_hash() -> str:
    from backend.shared.paths import project_root
    root = project_root()
    digest = hashlib.sha256()
    for relative in FEATURE_PROVENANCE_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def _economic_event_vector(grid: Tensor) -> Tensor:
    n_wells = grid.shape[1]
    available = grid[:, :, 15] > 0.5
    opened = grid[:, :, 19] > 0.5
    producer = available & opened & (grid[:, :, 17] > 0.5)
    injector = available & opened & (grid[:, :, 18] > 0.5)
    state = torch.where(
        producer,
        torch.ones_like(grid[:, :, 0], dtype=torch.long),
        torch.where(
            injector,
            torch.full_like(grid[:, :, 0], 2, dtype=torch.long),
            torch.zeros_like(grid[:, :, 0], dtype=torch.long),
        ),
    )
    per_well = []
    for well in range(n_wells):
        values = state[:, well].tolist()
        last_active = 0
        previous = 0
        seen_active = False
        launches = restarts = conversions = reverse_conversions = shutdowns = 0
        post_active_shut = 0
        first_active = N_INTERVALS - 1
        first_injection = N_INTERVALS - 1
        for step, current in enumerate(values):
            if current == 0:
                if seen_active:
                    post_active_shut += 1
                if previous:
                    shutdowns += 1
            else:
                if not seen_active:
                    launches += 1
                    first_active = step
                elif current != last_active:
                    if last_active == 1 and current == 2:
                        conversions += 1
                    elif last_active == 2 and current == 1:
                        reverse_conversions += 1
                elif previous == 0:
                    restarts += 1
                if current == 2 and first_injection == N_INTERVALS - 1:
                    first_injection = step
                seen_active = True
                last_active = current
            previous = current
        prod_mask = producer[:, well]
        inj_mask = injector[:, well]
        effective = grid[:, well, 1]
        zero = effective.new_zeros(())
        per_well.append(
            torch.stack(
                (
                    prod_mask.to(grid.dtype).mean(),
                    inj_mask.to(grid.dtype).mean(),
                    grid.new_tensor(post_active_shut / N_INTERVALS),
                    grid.new_tensor(float(launches)),
                    grid.new_tensor(float(restarts)),
                    grid.new_tensor(float(conversions)),
                    grid.new_tensor(float(reverse_conversions)),
                    grid.new_tensor(float(shutdowns)),
                    grid.new_tensor(first_active / (N_INTERVALS - 1)),
                    grid.new_tensor(first_injection / (N_INTERVALS - 1)),
                    grid[-1, well, 2],
                    grid[-1, well, 3],
                    effective[prod_mask].amax() if bool(prod_mask.any()) else zero,
                    effective[inj_mask].amax() if bool(inj_mask.any()) else zero,
                )
            )
        )
    matrix = torch.stack(per_well)
    if matrix.shape != (n_wells, ECONOMIC_WELL_FEATURES):
        raise ScenarioNpvHeadError("economic event feature width differs")
    aggregate = torch.cat(
        (
            matrix.mean(dim=0),
            matrix.std(dim=0, unbiased=False),
            matrix.amax(dim=0),
            matrix.sum(dim=0),
        )
    )
    return torch.cat((aggregate, matrix.reshape(-1)))


def scenario_feature_vector(
    x: Tensor,
    well_index: Tensor,
    *,
    n_wells: int,
    feature_set: FeatureSet = "full",
) -> Tensor:
    if x.ndim != 2 or x.shape[1] < BASE_FEATURES:
        raise ScenarioNpvHeadError(
            f"expected x[:, >={BASE_FEATURES}], got {x.shape}"
        )
    if len(x) != N_INTERVALS * n_wells or well_index.shape != (len(x),):
        raise ScenarioNpvHeadError("the scenario tensor does not cover 224 × wells")
    if n_wells < 1:
        raise ScenarioNpvHeadError("n_wells must be positive")
    if bool(((well_index < 0) | (well_index >= n_wells)).any()):
        raise ScenarioNpvHeadError("the well index is out of the allowed range")
    base = x[:, :BASE_FEATURES].to(dtype=torch.float64)
    step_index = torch.round(base[:, 11] * (N_INTERVALS - 1)).to(torch.long)
    if bool(((step_index < 0) | (step_index >= N_INTERVALS)).any()):
        raise ScenarioNpvHeadError("the calendar index is outside 0…223")
    flat_index = step_index * n_wells + well_index.to(torch.long)
    if len(torch.unique(flat_index)) != len(flat_index):
        raise ScenarioNpvHeadError("the scenario tensor contains duplicate step × well entries")
    grid = torch.empty(
        N_INTERVALS * n_wells,
        BASE_FEATURES,
        dtype=torch.float64,
    )
    grid[flat_index] = base
    grid = grid.reshape(N_INTERVALS, n_wells, BASE_FEATURES)

    rows = grid.reshape(-1, BASE_FEATURES)
    global_features = torch.cat(
        (
            rows.mean(dim=0),
            rows.std(dim=0, unbiased=False),
            rows.amin(dim=0),
            rows.amax(dim=0),
        )
    )
    if feature_set == "global":
        return global_features

    if N_INTERVALS % TEMPORAL_BINS:
        raise ScenarioNpvHeadError("224 intervals are not divisible into temporal bins")
    bin_width = N_INTERVALS // TEMPORAL_BINS
    bins = grid.reshape(TEMPORAL_BINS, bin_width * n_wells, BASE_FEATURES)
    temporal = torch.cat(
        (bins.mean(dim=1), bins.std(dim=1, unbiased=False)), dim=1
    ).reshape(-1)
    if feature_set == "temporal":
        return torch.cat((global_features, temporal))

    if feature_set not in {"full", "economic", "well_temporal"}:
        raise ScenarioNpvHeadError(f"unknown feature_set={feature_set!r}")
    controls = grid[:, :, :8]
    by_well = torch.cat(
        (
            controls.mean(dim=0),
            controls.std(dim=0, unbiased=False),
        ),
        dim=1,
    ).reshape(-1)
    full = torch.cat((global_features, temporal, by_well))
    if feature_set == "full":
        return full
    if feature_set == "economic":
        return torch.cat((full, _economic_event_vector(grid)))

    well_temporal = grid.reshape(
        TEMPORAL_BINS,
        bin_width,
        n_wells,
        BASE_FEATURES,
    ).mean(dim=1)[:, :, :WELL_TEMPORAL_FEATURES]
    return torch.cat((full, well_temporal.reshape(-1)))
