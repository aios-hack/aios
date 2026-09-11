from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from backend.contexts.simulation.domain.errors import DatasetError
from backend.contexts.runs.domain.run_result import ResponseArtifact, RunStatus
from backend.contexts.schedule.domain.schedule import Schedule
from backend.shared.hashing import canonical_bytes
from backend.contexts.schedule.domain.validate import ValidationReport
from backend.contexts.simulation.domain.perturbation_design import (
    PerturbationFamily,
    PerturbationPlan,
    PerturbationSpec,
)

MANIFEST_NAME = "manifest.jsonl"
PLAN_NAME = "plan.json"
SCHEDULES_DIR = "schedules"

RETAINED_RUN_SUFFIXES: frozenset[str] = frozenset({".SMSPEC", ".UNSMRY"})
ALWAYS_RETAINED: tuple[str, ...] = (
    "materialized schedule of the scenario",
    "SMSPEC and UNSMRY of the run",
    "dataset manifest and plan",
)
COMPACTED_ON_REQUEST: tuple[str, ...] = (
    "remaining files of the run working directory",
    "deck directory of the scenario",
)

CORES_PER_CONTAINER = 4


def default_max_workers() -> int:
    cores = os.cpu_count() or CORES_PER_CONTAINER
    return max(1, cores // CORES_PER_CONTAINER)


@dataclass(frozen=True, slots=True)
class RunMetadata:
    scenario_id: str
    family: PerturbationFamily
    seed: int
    spec_hash: str
    canonical_schedule_hash: str
    deck_hash: str
    summary_hash: str
    run_id: str
    status: RunStatus
    unreachable_setpoint_fraction: float
    wallclock_seconds: float
    from_cache: bool
    synthetic: bool = False
    response_hash: str = ""
    message: str = ""

    def __post_init__(self) -> None:
        if self.synthetic:
            raise DatasetError(
                "synthetic=True is forbidden in the dataset channel (§9.2, §1.1): "
                "synthetic data is not admitted into quality metrics"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family.value,
            "seed": self.seed,
            "spec_hash": self.spec_hash,
            "canonical_schedule_hash": self.canonical_schedule_hash,
            "deck_hash": self.deck_hash,
            "summary_hash": self.summary_hash,
            "run_id": self.run_id,
            "status": self.status.value,
            "unreachable_setpoint_fraction": self.unreachable_setpoint_fraction,
            "wallclock_seconds": self.wallclock_seconds,
            "from_cache": self.from_cache,
            "synthetic": self.synthetic,
            "response_hash": self.response_hash,
            "message": self.message,
        }

    @staticmethod
    def from_json(data: Mapping[str, object]) -> "RunMetadata":
        return RunMetadata(
            scenario_id=str(data["scenario_id"]),
            family=PerturbationFamily(str(data["family"])),
            seed=int(data["seed"]),  # type: ignore[arg-type]
            spec_hash=str(data["spec_hash"]),
            canonical_schedule_hash=str(data["canonical_schedule_hash"]),
            deck_hash=str(data["deck_hash"]),
            summary_hash=str(data["summary_hash"]),
            run_id=str(data["run_id"]),
            status=RunStatus(str(data["status"])),
            unreachable_setpoint_fraction=float(
                data["unreachable_setpoint_fraction"]  # type: ignore[arg-type]
            ),
            wallclock_seconds=float(data["wallclock_seconds"]),  # type: ignore[arg-type]
            from_cache=bool(data["from_cache"]),
            synthetic=bool(data.get("synthetic", False)),
            response_hash=str(data.get("response_hash", "")),
            message=str(data.get("message", "")),
        )


@dataclass(frozen=True, slots=True)
class DatasetSample:
    schedule: Schedule
    response: ResponseArtifact | None
    metadata: RunMetadata


@dataclass(frozen=True, slots=True)
class SkippedScenario:
    spec: PerturbationSpec
    report: ValidationReport


@dataclass(frozen=True, slots=True)
class DatasetBuildReport:
    dataset_hash: str
    plan_hash: str
    samples: tuple[DatasetSample, ...] = field(default_factory=tuple)
    failed: tuple[RunMetadata, ...] = field(default_factory=tuple)
    skipped: tuple[SkippedScenario, ...] = field(default_factory=tuple)
    wallclock_seconds: float = 0.0

    @property
    def n_from_cache(self) -> int:
        return sum(1 for sample in self.samples if sample.metadata.from_cache)

    @property
    def n_simulated(self) -> int:
        return sum(1 for sample in self.samples if not sample.metadata.from_cache)

    def by_family(self) -> dict[PerturbationFamily, int]:
        counts: dict[PerturbationFamily, int] = {}
        for sample in self.samples:
            family = sample.metadata.family
            counts[family] = counts.get(family, 0) + 1
        return counts


def dataset_hash(plan: PerturbationPlan, metadata: Iterable[RunMetadata]) -> str:
    keys = sorted(
        {
            f"{item.scenario_id}:{item.canonical_schedule_hash}:"
            f"{item.deck_hash}:{item.summary_hash}"
            for item in metadata
        }
    )
    payload = canonical_bytes({"plan_hash": plan.plan_hash, "runs": keys})
    return hashlib.sha256(payload).hexdigest()


class DatasetManifest:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, metadata: RunMetadata) -> None:
        line = json.dumps(metadata.to_json(), ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def read(self) -> tuple[RunMetadata, ...]:
        if not self.path.is_file():
            return ()
        records: list[RunMetadata] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(RunMetadata.from_json(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return tuple(records)

    def completed_scenarios(self) -> frozenset[str]:
        return frozenset(
            item.scenario_id for item in self.read() if item.status is RunStatus.OK
        )

