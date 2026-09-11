from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

from backend.contexts.constraints.domain.constraints import Constraints
from backend.shared.hashing import canonical_bytes

from backend.contexts.robustness.domain.perturbation import (
    ORGANIZER_KINDS,
    Perturbation,
    PerturbationKind,
)


class Split(Enum):
    DEV = "dev"
    HOLDOUT = "holdout"


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    split: Split
    description: str
    perturbations: tuple[Perturbation, ...]

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario without an identifier")
        if not self.description:
            raise ValueError(f"{self.scenario_id}: scenario without a case description")
        if not self.perturbations:
            raise ValueError(
                f"{self.scenario_id}: a scenario without perturbations coincides "
                f"with the nominal one and measures nothing"
            )

    @property
    def kinds(self) -> tuple[PerturbationKind, ...]:
        return tuple(p.kind for p in self.perturbations)

    def constraints(self, base: Constraints | None = None) -> Constraints:
        document = base if base is not None else Constraints()
        for perturbation in self.perturbations:
            document = perturbation.apply(document)
        return document


@dataclass(frozen=True, slots=True)
class FragilityBattery:
    scenarios: tuple[Scenario, ...]
    seed: int
    version: str

    def __post_init__(self) -> None:
        if not self.scenarios:
            raise ValueError("an empty battery measures nothing")
        if not self.version:
            raise ValueError("battery without a version: the artifact is indistinguishable from another")
        identifiers = [s.scenario_id for s in self.scenarios]
        duplicates = sorted(
            {name for name in identifiers if identifiers.count(name) > 1}
        )
        if duplicates:
            raise ValueError(f"duplicate scenario identifiers: {duplicates}")
        for split in Split:
            if not self.of(split):
                raise ValueError(
                    f"split «{split.value}» is empty: without a dev/holdout separation "
                    f"robustness is measured on the same battery that θ "
                    f"were fitted on"
                )
        missing = set(ORGANIZER_KINDS) - set(self.kinds())
        if missing:
            raise ValueError(
                f"the battery does not cover the organizer perturbation kinds: "
                f"{sorted(k.value for k in missing)}"
            )

    def of(self, split: Split) -> tuple[Scenario, ...]:
        return tuple(s for s in self.scenarios if s.split is split)

    def dev(self) -> tuple[Scenario, ...]:
        return self.of(Split.DEV)

    def holdout(self) -> tuple[Scenario, ...]:
        return self.of(Split.HOLDOUT)

    def by_id(self, scenario_id: str) -> Scenario:
        for scenario in self.scenarios:
            if scenario.scenario_id == scenario_id:
                return scenario
        raise ValueError(f"scenario {scenario_id} is not in the battery")

    def kinds(self) -> tuple[PerturbationKind, ...]:
        seen: list[PerturbationKind] = []
        for scenario in self.scenarios:
            for kind in scenario.kinds:
                if kind not in seen:
                    seen.append(kind)
        return tuple(seen)

    def kinds_of(self, split: Split) -> tuple[PerturbationKind, ...]:
        seen: list[PerturbationKind] = []
        for scenario in self.of(split):
            for kind in scenario.kinds:
                if kind not in seen:
                    seen.append(kind)
        return tuple(seen)

    def constraints_by_scenario(
        self, base: Constraints | None = None
    ) -> dict[str, Constraints]:
        return {s.scenario_id: s.constraints(base) for s in self.scenarios}

    def battery_hash(self) -> str:
        payload = {
            "version": self.version,
            "seed": self.seed,
            "scenarios": [
                {
                    "scenario_id": s.scenario_id,
                    "split": s.split.value,
                    "description": s.description,
                    "constraints": s.constraints(),
                }
                for s in sorted(self.scenarios, key=lambda s: s.scenario_id)
            ],
        }
        return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def split_by_declaration(
    scenarios: Iterable[Scenario], holdout_ids: Sequence[str]
) -> tuple[Scenario, ...]:
    declared = set(holdout_ids)
    resolved: list[Scenario] = []
    for scenario in scenarios:
        target = Split.HOLDOUT if scenario.scenario_id in declared else Split.DEV
        declared.discard(scenario.scenario_id)
        resolved.append(
            Scenario(
                scenario_id=scenario.scenario_id,
                split=target,
                description=scenario.description,
                perturbations=scenario.perturbations,
            )
        )
    if declared:
        raise ValueError(f"holdout declares scenarios that do not exist: {sorted(declared)}")
    return tuple(resolved)


def coverage_report(battery: FragilityBattery) -> Mapping[str, tuple[str, ...]]:
    return {
        split.value: tuple(k.value for k in battery.kinds_of(split))
        for split in Split
    }
