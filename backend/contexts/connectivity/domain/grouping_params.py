from __future__ import annotations

from dataclasses import dataclass

GROUP_PREFIX = "G"
MERGE_OVERLAP_DEFAULT = 0.5
MEMBERSHIP_SHARE_DEFAULT = MERGE_OVERLAP_DEFAULT / 2.0


@dataclass(frozen=True, slots=True)
class GroupingParams:
    merge_overlap: float = MERGE_OVERLAP_DEFAULT
    membership_share: float = MEMBERSHIP_SHARE_DEFAULT
    seed: int = 0
    weight_quantile: float | None = None

    def __post_init__(self) -> None:
        if not (0.0 < self.merge_overlap <= 1.0):
            raise ValueError(
                f"merge threshold {self.merge_overlap} outside (0, 1]: at zero "
                f"the entire stock merges into a single group"
            )
        if not (0.0 < self.membership_share <= 1.0):
            raise ValueError(
                f"membership threshold {self.membership_share} outside (0, 1]"
            )
        if self.weight_quantile is not None and not (
            0.0 <= self.weight_quantile < 1.0
        ):
            raise ValueError(
                f"weight quantile {self.weight_quantile} outside [0, 1): at one "
                f"every connection is cut off, the strongest included, and "
                f"nothing is left to merge"
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
    weight_quantile: float | None = None
    weight_cut: float | None = None
    largest_group: int = 0
    kept_edges: int = 0

    @property
    def collapsed(self) -> bool:
        return self.n_groups == 1

    def __post_init__(self) -> None:
        if self.coverage != self.n_wells:
            raise ValueError(
                f"coverage {self.coverage} of {self.n_wells}: every well must fall "
                f"into at least one group"
            )
