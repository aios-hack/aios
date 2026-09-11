from __future__ import annotations

from dataclasses import (
    dataclass,
)
from typing import Mapping, Sequence


FINALIST_CAP = 4


@dataclass(frozen=True, slots=True)
class IncumbentRecord:

    sequence: int
    stage: str
    schedule_hash: str
    npv_predicted: float
    theta: dict[str, float]
    ood_score: float | None
    ood_worst: str | None
    static_violations: int
    dynamic_blocking_violations: int
    physics_admissible: bool
    self_consistent: bool
    ood_exceedances: tuple[dict[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "stage": self.stage,
            "schedule_hash": self.schedule_hash,
            "npv_predicted": self.npv_predicted,
            "theta": dict(self.theta),
            "ood_score": self.ood_score,
            "ood_worst": self.ood_worst,
            "ood_exceedances": [dict(item) for item in self.ood_exceedances],
            "static_violations": self.static_violations,
            "dynamic_blocking_violations": self.dynamic_blocking_violations,
            "physics_admissible": self.physics_admissible,
            "self_consistent": self.self_consistent,
        }


class IncumbentRegistry:

    def __init__(self) -> None:
        self._records: list[IncumbentRecord] = []

    def promote(
        self,
        *,
        stage: str,
        schedule_hash: str,
        npv_predicted: float,
        theta: Mapping[str, float],
        ood_score: float | None,
        ood_worst: str | None,
        static_violations: int,
        dynamic_blocking_violations: int,
        physics_admissible: bool,
        self_consistent: bool,
        ood_exceedances: Sequence[Mapping[str, object]] = (),
    ) -> IncumbentRecord:
        record = IncumbentRecord(
            sequence=len(self._records),
            stage=stage,
            schedule_hash=schedule_hash,
            npv_predicted=float(npv_predicted),
            theta={name: float(value) for name, value in theta.items()},
            ood_score=None if ood_score is None else float(ood_score),
            ood_worst=ood_worst,
            static_violations=int(static_violations),
            dynamic_blocking_violations=int(dynamic_blocking_violations),
            physics_admissible=bool(physics_admissible),
            self_consistent=bool(self_consistent),
            ood_exceedances=tuple(dict(item) for item in ood_exceedances),
        )
        self._records.append(record)
        return record

    @property
    def records(self) -> tuple[IncumbentRecord, ...]:
        return tuple(self._records)

    @property
    def current(self) -> IncumbentRecord | None:
        return self._records[-1] if self._records else None

    def as_list(self) -> list[dict[str, object]]:
        return [record.as_dict() for record in self._records]


def incumbent_gate_passed(
    *,
    static_violations: int,
    dynamic_blocking_violations: int,
    ood_score: float | None,
    ood_threshold: float,
    physics_admissible: bool,
    ood_soft_penalty: bool = False,
) -> bool:
    if static_violations > 0:
        return False
    if dynamic_blocking_violations > 0:
        return False
    if not physics_admissible:
        return False
    if ood_score is None:
        return False
    if ood_soft_penalty:
        return True
    return ood_score <= ood_threshold


def _physics_admissible(physics: Mapping[str, int]) -> bool:
    if not physics:
        return False
    return bool(physics.get("admissible", 0))


__all__ = [
    "FINALIST_CAP",
    "IncumbentRecord",
    "IncumbentRegistry",
    "incumbent_gate_passed",
]
