from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.constraints.domain.schema import DEFAULT_CONNECTIVITY_MEASUREMENT

DEFAULT_LAGS = (0, 1, 2, 3, 4, 5, 6)

DEFAULT_RIDGE = 1e-6

DEFAULT_MEASUREMENT_PARAMS = DEFAULT_CONNECTIVITY_MEASUREMENT

MEASURE_CODE_VERSION = "connectivity.measure/1"

ARTIFACT_FORMAT = "lambda/1"

PROVENANCE_FIELDS: tuple[str, ...] = (
    "artifact_id",
    "measured_at",
    "n_runs",
    "source_run_ids",
    "code_version",
)


@dataclass(frozen=True, slots=True)
class MeasurementReport:
    influence: Lambda
    lag_scan: tuple[tuple[int, float], ...]
    n_runs_by_batch: tuple[int, ...]
    unreachable: tuple[str, ...]
    unmoved: tuple[str, ...] = ()

    @property
    def nonzero_edges(self) -> int:
        return sum(
            1 for row in self.influence.matrix for value in row if abs(value) > 0.0
        )


class CampaignMetadata(Protocol):
    scenario_id: str


class CampaignSample(Protocol):
    response: ResponseArtifact | None
    metadata: CampaignMetadata
