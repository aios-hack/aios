from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Sequence

from aios_backend.core.contracts import Groups, Lambda, canonical_bytes

GROUP_PREFIX = "G"
MERGE_OVERLAP_DEFAULT = 0.5
MEMBERSHIP_SHARE_DEFAULT = MERGE_OVERLAP_DEFAULT / 2.0


@dataclass(frozen=True, slots=True)
class GroupingParams:
    merge_overlap: float = MERGE_OVERLAP_DEFAULT
    membership_share: float = MEMBERSHIP_SHARE_DEFAULT
    seed: int = 0

    def __post_init__(self) -> None:
        if not (0.0 < self.merge_overlap <= 1.0):
            raise ValueError(
                f"порог слияния {self.merge_overlap} вне (0, 1]: при нуле "
                f"весь фонд сливается в один участок"
            )
        if not (0.0 < self.membership_share <= 1.0):
            raise ValueError(
                f"порог принадлежности {self.membership_share} вне (0, 1]"
            )


@dataclass(frozen=True, slots=True)
class GroupingReport:
    n_groups: int
    n_wells: int
    n_producers: int
    n_injectors: int
    coverage: int
    overlapped_wells: tuple[str, ...]
    isolated_producers: tuple[str, ...]
    dual_role_wells: tuple[str, ...]
    merged_injector_pairs: tuple[tuple[str, str], ...]
    degenerate: bool

    def __post_init__(self) -> None:
        if self.coverage != self.n_wells:
            raise ValueError(
                f"покрытие {self.coverage} из {self.n_wells}: каждая скважина "
                f"обязана попасть хотя бы в один участок"
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


def _merge_injectors(
    influence: Lambda, params: GroupingParams
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, str], ...]]:
    injectors = influence.injectors
    columns = {
        well: _positive(_column(influence.matrix, index))
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
    assigned: dict[int, list[str]] = {i: [] for i in range(len(clusters))}
    isolated: list[str] = []
    for row, producer in enumerate(influence.producers):
        weights: list[float] = []
        for cluster in clusters:
            weight = sum(
                max(influence.matrix[row][index_of[well]], 0.0)
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


def build_groups(
    influence: Lambda,
    params: GroupingParams | None = None,
    extra_wells: Sequence[str] = (),
) -> tuple[Groups, GroupingReport]:
    settings = GroupingParams() if params is None else params
    fund = tuple(
        sorted(set(influence.producers) | set(influence.injectors) | set(extra_wells))
    )
    if not fund:
        raise ValueError(
            "фонд пуст: нарезать на участки нечего, нулевая λ без единой "
            "скважины не является вырожденным случаем — это отсутствие данных"
        )
    dual_role = tuple(
        sorted(set(influence.producers) & set(influence.injectors))
    )

    if not influence.injectors:
        raise ValueError(
            "в окне λ нет ни одной нагнетательной: каждый участок обязан "
            "содержать нагнетательную, а брать её неоткуда"
        )

    clusters, merged_pairs = _merge_injectors(influence, settings)
    assigned, isolated = _producer_membership(influence, clusters, settings)

    width = _id_width(len(clusters))
    groups: dict[str, tuple[str, ...]] = {}
    for ordinal, cluster in enumerate(clusters, start=1):
        members = set(cluster) | set(assigned[ordinal - 1])
        groups[_group_id(ordinal, width)] = tuple(sorted(members))

    homeless = tuple(
        sorted(
            well
            for well in fund
            if not any(well in members for members in groups.values())
        )
    )
    degenerate = bool(homeless)
    if homeless:
        host = _group_id(1, width)
        groups[host] = tuple(sorted(set(groups[host]) | set(homeless)))

    covered = {well for members in groups.values() for well in members}
    overlapped = tuple(
        sorted(
            well
            for well in covered
            if sum(1 for members in groups.values() if well in members) > 1
        )
    )
    report = GroupingReport(
        n_groups=len(groups),
        n_wells=len(fund),
        n_producers=len(influence.producers),
        n_injectors=len(influence.injectors),
        coverage=len(covered),
        overlapped_wells=overlapped,
        isolated_producers=isolated,
        dual_role_wells=dual_role,
        merged_injector_pairs=merged_pairs,
        degenerate=degenerate,
    )
    artifact = Groups(
        groups=groups,
        lambda_hash=lambda_hash(influence),
        group_hash=group_hash(groups, influence, settings),
    )
    validate_groups(artifact, influence, fund)
    return artifact, report


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
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def validate_groups(
    artifact: Groups, influence: Lambda, fund: Sequence[str]
) -> None:
    if not artifact.groups:
        raise ValueError("нарезка пуста")
    injectors = set(influence.injectors)
    for group_id, members in sorted(artifact.groups.items()):
        if not members:
            raise ValueError(f"участок {group_id} пуст")
        if not set(members) & injectors:
            raise ValueError(
                f"участок {group_id} без нагнетательной: управлять закачкой "
                f"внутри него нечем"
            )
    covered = {well for members in artifact.groups.values() for well in members}
    missing = tuple(sorted(set(fund) - covered))
    if missing:
        raise ValueError(
            f"вне участков осталось {len(missing)} скважин: {missing}"
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
