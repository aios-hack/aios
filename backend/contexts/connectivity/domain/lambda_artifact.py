from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.connectivity.domain.errors import CampaignError
from backend.contexts.connectivity.domain.groups import lambda_hash
from backend.contexts.connectivity.domain.measurement_report import (
    ARTIFACT_FORMAT,
    MEASURE_CODE_VERSION,
    PROVENANCE_FIELDS,
    MeasurementReport,
)
from backend.shared.json_io import read_json

def artifact_id(influence: Lambda) -> str:
    return lambda_hash(influence)


@dataclass(frozen=True, slots=True)
class LambdaProvenance:
    artifact_id: str | None
    measured_at: date | None
    n_runs: int | None
    source_run_ids: tuple[str, ...] | None
    code_version: str | None

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in PROVENANCE_FIELDS
            if getattr(self, name) is None
        )

    @property
    def is_recorded(self) -> bool:
        return not self.missing_fields


UNRECORDED_PROVENANCE = LambdaProvenance(
    artifact_id=None,
    measured_at=None,
    n_runs=None,
    source_run_ids=None,
    code_version=None,
)


def save_lambda(
    measured: MeasurementReport,
    path: Path,
    *,
    measured_at: date,
    source_run_ids: Sequence[str],
    code_version: str = MEASURE_CODE_VERSION,
) -> Path:
    influence = measured.influence
    runs = tuple(str(run_id) for run_id in source_run_ids)
    if not runs:
        raise CampaignError(
            f"{path}: lambda provenance without a single run identifier — an "
            f"artifact whose provenance cannot be confirmed is not written"
        )
    if len(set(runs)) != len(runs):
        raise CampaignError(
            f"{path}: run identifiers repeat, the number of runs cannot be "
            f"counted from this list"
        )
    path.write_text(
        json.dumps(
            {
                "artifact_format": ARTIFACT_FORMAT,
                "artifact_id": artifact_id(influence),
                "measured_at": measured_at.isoformat(),
                "n_runs": len(runs),
                "source_run_ids": list(runs),
                "code_version": code_version,
                "window_start": influence.window_start.isoformat(),
                "window_end": influence.window_end.isoformat(),
                "lag_months": influence.lag_months,
                "amplitude": influence.amplitude,
                "rank": influence.rank,
                "condition_number": influence.condition_number,
                "stability": influence.stability,
                "producers": list(influence.producers),
                "injectors": list(influence.injectors),
                "matrix": [list(row) for row in influence.matrix],
                "achievability_ok": dict(influence.achievability_ok),
                "lag_scan": [list(item) for item in measured.lag_scan],
                "n_runs_by_batch": list(measured.n_runs_by_batch),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _read_lambda_payload(path: Path | str) -> tuple[Path, dict]:
    resolved = Path(path)
    if not resolved.is_file():
        raise CampaignError(
            f"no measured lambda at {resolved}: the measurement campaign "
            "(application connectivity campaign) has not run yet, and "
            f"substituting a zero matrix for a measurement is forbidden"
        )
    return resolved, read_json(resolved)


def _lambda_from_payload(data: Mapping[str, object]) -> Lambda:
    return Lambda(
        window_start=date.fromisoformat(str(data["window_start"])),
        window_end=date.fromisoformat(str(data["window_end"])),
        producers=tuple(data["producers"]),
        injectors=tuple(data["injectors"]),
        matrix=tuple(tuple(float(value) for value in row) for row in data["matrix"]),
        lag_months=int(data["lag_months"]),
        amplitude=float(data["amplitude"]),
        stability=float(data["stability"]),
        rank=int(data["rank"]),
        condition_number=float(data["condition_number"]),
        achievability_ok={
            well: bool(ok) for well, ok in data["achievability_ok"].items()
        },
    )


def _provenance_from_payload(
    resolved: Path, data: Mapping[str, object]
) -> LambdaProvenance:
    raw_measured_at = data.get("measured_at")
    measured_at: date | None = None
    if raw_measured_at is not None:
        try:
            measured_at = date.fromisoformat(str(raw_measured_at))
        except ValueError as error:
            raise CampaignError(
                f"{resolved}: the measured_at field {raw_measured_at!r} does not read "
                f"as a date — the artifact provenance can neither be confirmed "
                f"nor replaced by today's date"
            ) from error

    raw_runs = data.get("source_run_ids")
    source_run_ids: tuple[str, ...] | None = None
    if raw_runs is not None:
        if not isinstance(raw_runs, (list, tuple)):
            raise CampaignError(
                f"{resolved}: the source_run_ids field is not a list of identifiers"
            )
        source_run_ids = tuple(str(run_id) for run_id in raw_runs)

    raw_n_runs = data.get("n_runs")
    n_runs: int | None = None
    if raw_n_runs is not None:
        n_runs = int(raw_n_runs)
        if source_run_ids is not None and n_runs != len(source_run_ids):
            raise CampaignError(
                f"{resolved}: n_runs={n_runs} is recorded against "
                f"{len(source_run_ids)} run identifiers — the run count "
                f"disagrees with the list, neither can be trusted"
            )

    raw_artifact_id = data.get("artifact_id")
    raw_code_version = data.get("code_version")
    return LambdaProvenance(
        artifact_id=None if raw_artifact_id is None else str(raw_artifact_id),
        measured_at=measured_at,
        n_runs=n_runs,
        source_run_ids=source_run_ids,
        code_version=None if raw_code_version is None else str(raw_code_version),
    )


def load_lambda(path: Path | str) -> Lambda:
    resolved, data = _read_lambda_payload(path)
    return _lambda_from_payload(data)


def load_lambda_provenance(path: Path | str) -> LambdaProvenance:
    resolved, data = _read_lambda_payload(path)
    return _provenance_from_payload(resolved, data)


def load_lambda_with_provenance(path: Path | str) -> tuple[Lambda, LambdaProvenance]:
    resolved, data = _read_lambda_payload(path)
    return _lambda_from_payload(data), _provenance_from_payload(resolved, data)


def verify_artifact_id(path: Path | str) -> bool:
    influence, provenance = load_lambda_with_provenance(path)
    if provenance.artifact_id is None:
        raise CampaignError(
            f"{Path(path)}: artifact_id is not recorded, there is nothing to "
            f"check against — provenance metadata has not been written into "
            f"this artifact yet"
        )
    return provenance.artifact_id == artifact_id(influence)
