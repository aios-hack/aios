from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Lambda:

    window_start: date
    window_end: date
    producers: tuple[str, ...]
    injectors: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    lag_months: int
    amplitude: float
    stability: float
    rank: int
    condition_number: float
    achievability_ok: dict[str, bool]

    def __post_init__(self) -> None:
        if len(self.matrix) != len(self.producers):
            raise ValueError("matrix.rows != len(producers)")
        if self.matrix and len(self.matrix[0]) != len(self.injectors):
            raise ValueError("matrix.cols != len(injectors)")


@dataclass(frozen=True, slots=True)
class Groups:

    groups: dict[str, tuple[str, ...]]
    lambda_hash: str
    group_hash: str
