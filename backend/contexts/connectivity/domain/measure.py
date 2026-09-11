from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Sequence

from backend.contexts.reservoir.domain.response import StateAtDate
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.connectivity.domain.campaign_plan import (
    BATCHES_PER_HALF,
    T0_DECK_DATE_INDEX,
    CampaignSetup,
    level_factor,
)
from backend.contexts.connectivity.domain.errors import CampaignError
from backend.contexts.connectivity.domain.doe import DoEPlan, Level, achievability
from backend.contexts.connectivity.domain.estimator import (
    Batch,
    LaggedObservations,
    ProducerObservation,
    best_lag,
    estimate_lambda,
    realized_drive,
    scan_lag,
)
from backend.contexts.constraints.domain.schema import ConnectivityMeasurementParams
from backend.contexts.connectivity.domain.sweep import (
    WindowSteps,
    cumulative_liquid,
    mean_injection_rate,
)
from backend.contexts.connectivity.domain.measurement_report import (
    ARTIFACT_FORMAT,
    DEFAULT_MEASUREMENT_PARAMS,
    MEASURE_CODE_VERSION,
    PROVENANCE_FIELDS,
    CampaignMetadata,
    CampaignSample,
    MeasurementReport,
)
from backend.contexts.connectivity.domain.lambda_artifact import (
    UNRECORDED_PROVENANCE,
    LambdaProvenance,
    artifact_id,
    load_lambda,
    load_lambda_provenance,
    load_lambda_with_provenance,
    save_lambda,
    verify_artifact_id,
)
from backend.contexts.connectivity.domain.lambda_window import (
    EXTRAPOLATION,
    PARTIAL_EXTRAPOLATION,
    WITHIN_WINDOW,
    WindowApplicability,
    window_applicability,
)

if TYPE_CHECKING:
    from backend.contexts.simulation.infrastructure.dataset_manifest import DatasetSample

DEFAULT_LAGS = (0, 1, 2, 3, 4, 5, 6)

DEFAULT_RIDGE = 1e-6

__all__ = [
    "ARTIFACT_FORMAT",
    "DEFAULT_LAGS",
    "DEFAULT_MEASUREMENT_PARAMS",
    "DEFAULT_RIDGE",
    "EXTRAPOLATION",
    "MEASURE_CODE_VERSION",
    "PARTIAL_EXTRAPOLATION",
    "PROVENANCE_FIELDS",
    "UNRECORDED_PROVENANCE",
    "WITHIN_WINDOW",
    "CampaignMetadata",
    "CampaignSample",
    "LambdaProvenance",
    "MeasurementReport",
    "WindowApplicability",
    "artifact_id",
    "load_lambda",
    "load_lambda_provenance",
    "load_lambda_with_provenance",
    "measure",
    "save_lambda",
    "verify_artifact_id",
    "window_applicability",
]


def _samples_by_scenario(samples: Sequence[CampaignSample]) -> dict[str, CampaignSample]:
    return {sample.metadata.scenario_id: sample for sample in samples}


def _batch_samples(
    samples: Sequence[CampaignSample], batch: int, plan: DoEPlan
) -> tuple[CampaignSample, ...]:
    by_id = _samples_by_scenario(samples)
    ordered: list[CampaignSample] = []
    for row in plan.rows:
        scenario_id = f"lambda-b{batch}-{row.run_index:04d}"
        sample = by_id.get(scenario_id)
        if sample is None:
            raise CampaignError(
                f"batch {batch}: run {scenario_id} is missing. A plan row without a "
                f"response is a hole in the drive matrix, and there is nothing "
                f"to fill it with"
            )
        if sample.response is None:
            raise CampaignError(f"{scenario_id}: the response was not parsed")
        ordered.append(sample)
    return tuple(ordered)


def _injection_by_run(
    samples: Sequence[DatasetSample], injectors: Sequence[str], steps: WindowSteps
) -> tuple[dict[str, float], ...]:
    rows: list[dict[str, float]] = []
    for sample in samples:
        assert sample.response is not None
        states = sample.response.state_at_date
        rows.append(
            {
                well: mean_injection_rate(states, well, T0_DECK_DATE_INDEX, steps)
                for well in injectors
            }
        )
    return tuple(rows)


def _baseline_injection(
    states: Sequence[StateAtDate], injectors: Sequence[str], steps: WindowSteps
) -> dict[str, float]:
    return {
        well: mean_injection_rate(states, well, T0_DECK_DATE_INDEX, steps)
        for well in injectors
    }


def _targets_by_run(
    plan: DoEPlan, baseline_by_well: Mapping[str, float]
) -> tuple[dict[str, float], ...]:
    return tuple(
        {
            well: baseline_by_well[well] * level_factor(level, plan.amplitude)
            for well, level in row.levels.items()
        }
        for row in plan.rows
    )


def _observations(
    samples: Sequence[DatasetSample],
    baseline: ResponseArtifact,
    producers: Sequence[str],
    steps: WindowSteps,
    lag: int,
) -> LaggedObservations:
    shifted = WindowSteps(first=steps.first + lag, last=steps.last + lag)
    by_producer: dict[str, ProducerObservation] = {}
    for producer in producers:
        cumulative = tuple(
            cumulative_liquid(sample.response.interval_response, [producer], shifted)
            for sample in samples
            if sample.response is not None
        )
        by_producer[producer] = ProducerObservation(
            producer=producer,
            cumulative_by_run=cumulative,
            baseline_cumulative=cumulative_liquid(
                baseline.interval_response, [producer], shifted
            ),
        )
    return LaggedObservations(
        lag_months=lag, producers=tuple(producers), by_producer=by_producer
    )


def _movable(
    prepared: CampaignSetup,
    samples: Sequence[DatasetSample],
    injectors: Sequence[str],
    baseline_by_well: Mapping[str, float],
    steps: WindowSteps,
    separation_floor_share: float,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    floor = prepared.amplitude.step_m3_per_day * separation_floor_share
    by_id = _samples_by_scenario(samples)
    high: dict[str, list[float]] = {well: [] for well in injectors}
    low: dict[str, list[float]] = {well: [] for well in injectors}
    for batch, plan in enumerate(prepared.plans):
        for row in plan.rows:
            sample = by_id.get(f"lambda-b{batch}-{row.run_index:04d}")
            if sample is None or sample.response is None:
                continue
            for well, level in row.levels.items():
                rate = mean_injection_rate(
                    sample.response.state_at_date, well, T0_DECK_DATE_INDEX, steps
                )
                (high if level is Level.HIGH else low)[well].append(
                    rate - baseline_by_well[well]
                )
    moved: list[str] = []
    stuck: list[str] = []
    for well in injectors:
        if not high[well] or not low[well]:
            stuck.append(well)
            continue
        separation = sum(high[well]) / len(high[well]) - sum(low[well]) / len(low[well])
        (moved if separation >= floor else stuck).append(well)
    return tuple(moved), tuple(stuck)


def measure(
    prepared: CampaignSetup,
    samples: Sequence[CampaignSample],
    baseline: ResponseArtifact,
    *,
    n_steps: int,
    lags: Sequence[int] = DEFAULT_LAGS,
    ridge: float = DEFAULT_RIDGE,
    params: ConnectivityMeasurementParams = DEFAULT_MEASUREMENT_PARAMS,
) -> MeasurementReport:
    steps = WindowSteps(first=0, last=n_steps - 1)
    all_injectors = prepared.fund.injectors
    producers = prepared.fund.producers
    baseline_injection = _baseline_injection(baseline.state_at_date, all_injectors, steps)

    injectors, unmoved = _movable(
        prepared,
        samples,
        all_injectors,
        baseline_injection,
        steps,
        params.separation_floor_share,
    )
    if len(injectors) < 2:
        raise CampaignError(
            f"{len(injectors)} of {len(all_injectors)} injectors moved: there is "
            f"nothing to measure connectivity with"
        )

    half_drives = []
    half_samples = []
    unreachable: set[str] = set()
    for start in range(0, len(prepared.plans), BATCHES_PER_HALF):
        chunk = range(start, min(start + BATCHES_PER_HALF, len(prepared.plans)))
        pooled_samples: list[DatasetSample] = []
        pooled_actual: list[dict[str, float]] = []
        for batch in chunk:
            plan = prepared.plans[batch]
            ordered = _batch_samples(samples, batch, plan)
            actual_all = _injection_by_run(ordered, all_injectors, steps)
            report = achievability(
                plan,
                _targets_by_run(plan, baseline_injection),
                actual_all,
                params.injection_shortfall_tolerance,
            )
            unreachable.update(
                well for well, ok in report.achievability_ok().items() if not ok
            )
            pooled_samples.extend(ordered)
            pooled_actual.extend(
                {well: row[well] for well in injectors} for row in actual_all
            )
        half_drives.append(
            realized_drive(injectors, tuple(pooled_actual), baseline_injection)
        )
        half_samples.append(tuple(pooled_samples))

    if len(half_drives) < 2:
        raise CampaignError(
            f"{len(half_drives)} halves: stability is measured between two "
            f"independent halves, which needs {2 * BATCHES_PER_HALF} batches"
        )
    for index, drive in enumerate(half_drives):
        if drive.n_runs <= len(injectors):
            raise CampaignError(
                f"half {index}: {drive.n_runs} observations against "
                f"{len(injectors) + 1} regression parameters — the system is "
                f"underdetermined, R² will be one at any lag and the "
                f"coefficients are defined only up to the null space"
            )

    drives = half_drives
    batch_samples = half_samples

    scans = scan_lag(
        drives[0],
        {
            lag: _observations(batch_samples[0], baseline, producers, steps, lag)
            for lag in lags
        },
        ridge,
    )
    chosen = best_lag(scans)

    batches = tuple(
        Batch(
            drive=drives[index],
            observations=_observations(
                batch_samples[index], baseline, producers, steps, chosen.lag_months
            ),
        )
        for index in range(len(drives))
    )
    influence = estimate_lambda(
        window=prepared.window,
        producers=producers,
        batches=batches,
        lag_months=chosen.lag_months,
        amplitude=prepared.amplitude.step_m3_per_day,
        achievability_ok={well: well not in unreachable for well in injectors},
        ridge=ridge,
    )
    return MeasurementReport(
        influence=influence,
        lag_scan=tuple((scan.lag_months, scan.r_squared) for scan in scans),
        n_runs_by_batch=tuple(len(item) for item in batch_samples),
        unreachable=tuple(sorted(unreachable)),
        unmoved=unmoved,
    )
