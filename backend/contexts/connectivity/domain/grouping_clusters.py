from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

from backend.contexts.connectivity.domain.connectivity import Groups, Lambda
from backend.shared.hashing import canonical_bytes

from backend.contexts.connectivity.domain.grouping_params import (
    GROUP_PREFIX,
    GroupingParams,
)


def _column(matrix: Sequence[Sequence[float]], index: int) -> tuple[float, ...]:
    return tuple(row[index] for row in matrix)


def _positive(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(value if value > 0.0 else 0.0 for value in values)


def _overlap(left: Sequence[float], right: Sequence[float]) -> float:
    a = _positive(left)
    b = _positive(right)
    shared = sum(min(x, y) for x, y in zip(a, b))
    smaller = min(sum(a), sum(b))
    if smaller <= 0.0:
        return 0.0
    return shared / smaller


def weight_threshold(influence: Lambda, quantile: float) -> float:
    if not (0.0 <= quantile < 1.0):
        raise ValueError(
            f"weight quantile {quantile} outside [0, 1): a threshold that cuts off "
            f"every connection without exception is not a threshold"
        )
    weights = sorted(
        value for row in influence.matrix for value in row if value > 0.0
    )
    if not weights:
        raise ValueError(
            "lambda has no positive weight at all: there is nothing to compute the "
            "quantile from, and substituting a zero threshold would declare a "
            "matrix without a single connection to be dense"
        )
    position = quantile * (len(weights) - 1)
    low = int(position)
    high = min(low + 1, len(weights) - 1)
    share = position - low
    return weights[low] + (weights[high] - weights[low]) * share


def _thresholded(
    influence: Lambda, params: GroupingParams
) -> tuple[tuple[tuple[float, ...], ...], float | None]:
    if params.weight_quantile is None:
        return tuple(tuple(row) for row in influence.matrix), None
    cut = weight_threshold(influence, params.weight_quantile)
    return (
        tuple(
            tuple(value if value >= cut else 0.0 for value in row)
            for row in influence.matrix
        ),
        cut,
    )


def _merge_injectors(
    influence: Lambda, params: GroupingParams
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, str], ...]]:
    injectors = influence.injectors
    matrix, _ = _thresholded(influence, params)
    columns = {
        well: _positive(_column(matrix, index))
        for index, well in enumerate(injectors)
    }
    parent = {well: well for well in injectors}

    def find(well: str) -> str:
        root = well
        while parent[root] != root:
            root = parent[root]
        while parent[well] != root:
            parent[well], well = root, parent[well]
        return root

    merged: list[tuple[str, str]] = []
    for i, left in enumerate(injectors):
        for right in injectors[i + 1 :]:
            if _overlap(columns[left], columns[right]) < params.merge_overlap:
                continue
            merged.append((left, right))
            root_left, root_right = find(left), find(right)
            if root_left == root_right:
                continue
            if root_left <= root_right:
                parent[root_right] = root_left
            else:
                parent[root_left] = root_right

    clustered: dict[str, list[str]] = {}
    for well in injectors:
        clustered.setdefault(find(well), []).append(well)
    ordered = tuple(
        tuple(sorted(members)) for _, members in sorted(clustered.items())
    )
    return ordered, tuple(sorted(merged))


def _producer_membership(
    influence: Lambda,
    clusters: Sequence[Sequence[str]],
    params: GroupingParams,
) -> tuple[dict[int, list[str]], tuple[str, ...]]:
    index_of = {well: i for i, well in enumerate(influence.injectors)}
    matrix, _ = _thresholded(influence, params)
    assigned: dict[int, list[str]] = {i: [] for i in range(len(clusters))}
    isolated: list[str] = []
    for row, producer in enumerate(influence.producers):
        weights: list[float] = []
        for cluster in clusters:
            weight = sum(
                max(matrix[row][index_of[well]], 0.0)
                for well in cluster
            )
            weights.append(weight)
        total = sum(weights)
        if total <= 0.0:
            isolated.append(producer)
            continue
        best = max(range(len(weights)), key=lambda i: (weights[i], -i))
        for i, weight in enumerate(weights):
            if i == best or weight / total >= params.membership_share:
                assigned[i].append(producer)
    return assigned, tuple(sorted(isolated))


def _group_id(ordinal: int, width: int) -> str:
    return f"{GROUP_PREFIX}{ordinal:0{width}d}"


def _id_width(n_groups: int) -> int:
    return len(str(max(n_groups, 1)))

def lambda_hash(influence: Lambda) -> str:
    payload = {
        "window_start": influence.window_start,
        "window_end": influence.window_end,
        "producers": list(influence.producers),
        "injectors": list(influence.injectors),
        "matrix": [list(row) for row in influence.matrix],
        "lag_months": influence.lag_months,
        "amplitude": influence.amplitude,
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def group_hash(
    groups: Mapping[str, Sequence[str]],
    influence: Lambda,
    params: GroupingParams,
) -> str:
    payload = {
        "groups": {
            group_id: sorted(groups[group_id]) for group_id in sorted(groups)
        },
        "lambda_hash": lambda_hash(influence),
        "merge_overlap": params.merge_overlap,
        "membership_share": params.membership_share,
        "seed": params.seed,
    }
    if params.weight_quantile is not None:
        payload["weight_quantile"] = params.weight_quantile
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def validate_groups(
    artifact: Groups, influence: Lambda, fund: Sequence[str]
) -> None:
    if not artifact.groups:
        raise ValueError("the grouping is empty")
    injectors = set(influence.injectors)
    for group_id, members in sorted(artifact.groups.items()):
        if not members:
            raise ValueError(f"group {group_id} is empty")
        if not set(members) & injectors:
            raise ValueError(
                f"group {group_id} has no injector: there is no way to control "
                f"injection inside it"
            )
    covered = {well for members in artifact.groups.values() for well in members}
    missing = tuple(sorted(set(fund) - covered))
    if missing:
        raise ValueError(
            f"{len(missing)} wells are left outside the groups: {missing}"
        )


def coverage_of(artifact: Groups) -> int:
    return len({well for members in artifact.groups.values() for well in members})


def group_sizes(artifact: Groups) -> dict[str, int]:
    return {
        group_id: len(members)
        for group_id, members in sorted(artifact.groups.items())
    }


def _co_membership(artifact: Groups) -> dict[str, frozenset[str]]:
    neighbours: dict[str, set[str]] = {}
    for members in artifact.groups.values():
        for well in members:
            neighbours.setdefault(well, set()).update(
                other for other in members if other != well
            )
    return {well: frozenset(others) for well, others in neighbours.items()}


def moved_share(before: Groups, after: Groups) -> float:
    left = _co_membership(before)
    right = _co_membership(after)
    wells = set(left) | set(right)
    if not wells:
        return 0.0
    moved = sum(1 for well in wells if left.get(well) != right.get(well))
    return moved / len(wells)
