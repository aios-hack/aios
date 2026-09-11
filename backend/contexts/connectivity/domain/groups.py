from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backend.contexts.connectivity.domain.connectivity import Groups, Lambda

from backend.contexts.connectivity.domain.grouping_params import (
    GROUP_PREFIX,
    MEMBERSHIP_SHARE_DEFAULT,
    MERGE_OVERLAP_DEFAULT,
    GroupingParams,
    GroupingReport,
)
from backend.contexts.connectivity.domain.grouping_clusters import (
    _group_id,
    _id_width,
    _merge_injectors,
    _producer_membership,
    _thresholded,
    coverage_of,
    group_hash,
    group_sizes,
    lambda_hash,
    moved_share,
    validate_groups,
    weight_threshold,
)

__all__ = [
    "DEFAULT_QUANTILE_GRID",
    "GROUP_PREFIX",
    "MEMBERSHIP_SHARE_DEFAULT",
    "MERGE_OVERLAP_DEFAULT",
    "GroupingParams",
    "GroupingReport",
    "QuantileStep",
    "QuantileSweep",
    "build_groups",
    "coverage_of",
    "group_hash",
    "group_sizes",
    "lambda_hash",
    "moved_share",
    "sweep_quantiles",
    "validate_groups",
    "weight_threshold",
]


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
            "the well stock is empty: there is nothing to group; a zero lambda "
            "without a single well is not a degenerate case — it is missing data"
        )
    dual_role = tuple(
        sorted(set(influence.producers) & set(influence.injectors))
    )

    if not influence.injectors:
        raise ValueError(
            "the lambda window holds no injector at all: every group must contain "
            "an injector, and there is nowhere to take one from"
        )

    matrix, cut = _thresholded(influence, settings)
    kept_edges = sum(1 for row in matrix for value in row if value > 0.0)
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
        weight_quantile=settings.weight_quantile,
        weight_cut=cut,
        largest_group=max(len(members) for members in groups.values()),
        kept_edges=kept_edges,
    )
    artifact = Groups(
        groups=groups,
        lambda_hash=lambda_hash(influence),
        group_hash=group_hash(groups, influence, settings),
    )
    validate_groups(artifact, influence, fund)
    return artifact, report


DEFAULT_QUANTILE_GRID: tuple[float, ...] = (
    0.0,
    0.1,
    0.2,
    0.3,
    0.4,
    0.5,
    0.6,
    0.7,
    0.8,
    0.9,
    0.95,
    0.99,
)


@dataclass(frozen=True, slots=True)
class QuantileStep:
    quantile: float
    weight_cut: float
    n_groups: int
    largest_group: int
    kept_edges: int
    isolated_producers: int


@dataclass(frozen=True, slots=True)
class QuantileSweep:
    steps: tuple[QuantileStep, ...]
    n_wells: int
    baseline_groups: int

    @property
    def split_quantile(self) -> float | None:
        for step in self.steps:
            if step.n_groups > 1:
                return step.quantile
        return None

    @property
    def split_cut(self) -> float | None:
        for step in self.steps:
            if step.n_groups > 1:
                return step.weight_cut
        return None


def sweep_quantiles(
    influence: Lambda,
    quantiles: Sequence[float] = DEFAULT_QUANTILE_GRID,
    params: GroupingParams | None = None,
    extra_wells: Sequence[str] = (),
) -> QuantileSweep:
    if not quantiles:
        raise ValueError(
            "the quantile grid is empty: there is nothing to report the threshold "
            "at which the stock stops being a single group from"
        )
    base = GroupingParams() if params is None else params
    baseline_artifact, baseline_report = build_groups(influence, base, extra_wells)
    steps: list[QuantileStep] = []
    for quantile in sorted(quantiles):
        settings = GroupingParams(
            merge_overlap=base.merge_overlap,
            membership_share=base.membership_share,
            seed=base.seed,
            weight_quantile=quantile,
        )
        artifact, report = build_groups(influence, settings, extra_wells)
        cut = report.weight_cut
        if cut is None:
            raise ValueError(
                f"quantile {quantile}: the threshold was not computed, the grouping "
                f"report cannot be filled with an invented value"
            )
        steps.append(
            QuantileStep(
                quantile=quantile,
                weight_cut=cut,
                n_groups=report.n_groups,
                largest_group=report.largest_group,
                kept_edges=report.kept_edges,
                isolated_producers=len(report.isolated_producers),
            )
        )
    return QuantileSweep(
        steps=tuple(steps),
        n_wells=baseline_report.n_wells,
        baseline_groups=baseline_report.n_groups,
    )
