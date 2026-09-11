from __future__ import annotations

import json
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from backend.core.contracts import IntervalResponse, Lambda, ResponseArtifact, StateAtDate
from backend.shared.paths import data_root
from backend.contexts.connectivity.application.campaign import (
    BATCHES_PER_HALF,
    T0_DECK_DATE_INDEX,
    CampaignError,
    CampaignSetup,
    level_factor,
)
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
from backend.contexts.constraints.domain.schema import (
    DEFAULT_CONNECTIVITY_MEASUREMENT,
    ConnectivityMeasurementParams,
)
from backend.contexts.connectivity.domain.groups import GroupingParams, build_groups, lambda_hash
from backend.contexts.connectivity.domain.sweep import (
    WindowSteps,
    cumulative_liquid,
    mean_injection_rate,
)
from backend.shared.json_io import read_json

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
                f"партия {batch}: нет прогона {scenario_id}. Строка плана без "
                f"отклика — дыра в матрице воздействий, дозаполнять её нечем"
            )
        if sample.response is None:
            raise CampaignError(f"{scenario_id}: отклик не разобран")
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
            f"сдвинулось {len(injectors)} нагнетательных из {len(all_injectors)}: "
            f"измерять связность нечем"
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
            f"половин {len(half_drives)}: устойчивость меряется между двумя "
            f"независимыми половинами, партий для этого нужно "
            f"{2 * BATCHES_PER_HALF}"
        )
    for index, drive in enumerate(half_drives):
        if drive.n_runs <= len(injectors):
            raise CampaignError(
                f"половина {index}: наблюдений {drive.n_runs} при "
                f"{len(injectors) + 1} параметрах регрессии — система "
                f"недоопределена, R² будет единицей на любом лаге, а "
                f"коэффициенты определены с точностью до ядра"
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
            f"{path}: происхождение λ без единого идентификатора прогона — "
            f"артефакт, чьё происхождение нечем подтвердить, не записывается"
        )
    if len(set(runs)) != len(runs):
        raise CampaignError(
            f"{path}: идентификаторы прогонов повторяются, число прогонов "
            f"нельзя посчитать по этому списку"
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
            f"измеренной λ нет по пути {resolved}: кампания замера "
            "(application connectivity campaign) ещё не отрабатывала, "
            f"подставлять нулевую матрицу вместо измерения запрещено"
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
                f"{resolved}: поле measured_at «{raw_measured_at}» не читается "
                f"как дата — происхождение артефакта нельзя ни подтвердить, "
                f"ни заменить сегодняшним числом"
            ) from error

    raw_runs = data.get("source_run_ids")
    source_run_ids: tuple[str, ...] | None = None
    if raw_runs is not None:
        if not isinstance(raw_runs, (list, tuple)):
            raise CampaignError(
                f"{resolved}: поле source_run_ids не список идентификаторов"
            )
        source_run_ids = tuple(str(run_id) for run_id in raw_runs)

    raw_n_runs = data.get("n_runs")
    n_runs: int | None = None
    if raw_n_runs is not None:
        n_runs = int(raw_n_runs)
        if source_run_ids is not None and n_runs != len(source_run_ids):
            raise CampaignError(
                f"{resolved}: записано n_runs={n_runs} при "
                f"{len(source_run_ids)} идентификаторах прогонов — счёт "
                f"прогонов расходится со списком, доверять нечему"
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
            f"{Path(path)}: artifact_id не записан, сверять нечего — "
            f"метаданные происхождения в этот артефакт ещё не дописаны"
        )
    return provenance.artifact_id == artifact_id(influence)


WITHIN_WINDOW = "within-measurement"

EXTRAPOLATION = "extrapolation"

PARTIAL_EXTRAPOLATION = "partial-extrapolation"


@dataclass(frozen=True, slots=True)
class WindowApplicability:
    verdict: str
    lambda_window_start: date
    lambda_window_end: date
    horizon_start: date
    horizon_end: date
    months_before: int
    months_after: int
    covered_share: float

    @property
    def is_extrapolation(self) -> bool:
        return self.verdict != WITHIN_WINDOW

    @property
    def detail(self) -> str:
        window = f"{self.lambda_window_start}..{self.lambda_window_end}"
        horizon = f"{self.horizon_start}..{self.horizon_end}"
        if self.verdict == WITHIN_WINDOW:
            return (
                f"горизонт {horizon} лежит внутри окна измерения λ {window}: "
                f"матрица связности применяется там, где её мерили"
            )
        if self.verdict == EXTRAPOLATION:
            return (
                f"горизонт {horizon} целиком вне окна измерения λ {window}: "
                f"вся связность в плане — экстраполяция, ни один месяц "
                f"горизонта не покрыт замером"
            )
        return (
            f"окно измерения λ {window} покрывает "
            f"{self.covered_share:.1%} горизонта {horizon}: "
            f"{self.months_before} мес. до окна и {self.months_after} мес. "
            f"после него — экстраполяция"
        )

    def as_provenance(self) -> dict[str, str]:
        return {
            "lambda_window_applicability": self.verdict,
            "lambda_window_applicability_detail": self.detail,
            "lambda_window_measured": (
                f"{self.lambda_window_start}..{self.lambda_window_end}"
            ),
            "lambda_window_horizon": f"{self.horizon_start}..{self.horizon_end}",
            "lambda_window_covered_share": f"{self.covered_share:.4f}",
            "lambda_window_months_outside": str(
                self.months_before + self.months_after
            ),
        }


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def window_applicability(
    influence: Lambda, horizon: Sequence[date]
) -> WindowApplicability:
    if not horizon:
        raise CampaignError(
            "горизонт кейса пуст: сравнивать окно измерения λ не с чем, "
            "а объявлять применимость без горизонта нельзя"
        )
    horizon_start = min(horizon)
    horizon_end = max(horizon)
    window_start = influence.window_start
    window_end = influence.window_end
    if window_end < window_start:
        raise CampaignError(
            f"окно измерения λ {window_start}..{window_end} вывернуто: конец "
            f"раньше начала, применимость по такому окну не определена"
        )
    months_before = max(0, _months_between(horizon_start, window_start))
    months_after = max(0, _months_between(window_end, horizon_end))
    inside = sum(1 for moment in horizon if window_start <= moment <= window_end)
    covered_share = inside / len(horizon)
    if inside == 0:
        verdict = EXTRAPOLATION
    elif inside == len(horizon):
        verdict = WITHIN_WINDOW
    else:
        verdict = PARTIAL_EXTRAPOLATION
    return WindowApplicability(
        verdict=verdict,
        lambda_window_start=window_start,
        lambda_window_end=window_end,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        months_before=months_before,
        months_after=months_after,
        covered_share=covered_share,
    )
