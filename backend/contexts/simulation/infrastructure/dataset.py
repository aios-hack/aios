from __future__ import annotations

import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from backend.contexts.simulation.domain.errors import DatasetError
from backend.contexts.runs.domain.run_result import RunResult, RunStatus, SummarySpec
from backend.contexts.schedule.domain.schedule import Schedule
from backend.shared.hashing import hash_schedule
from backend.contexts.schedule.domain.validate import validate_static

from backend.contexts.simulation.infrastructure.cache import CachingOpmRunner, RunCache
from backend.contexts.simulation.domain.perturbation_design import (
    MaterializedSchedule,
    PerturbationPlan,
    dataset_base_schedule,
    materialize,
)
from backend.contexts.reservoir.infrastructure.opm_deck import EmittedOpmDeck, OpmDeckEmitter
from backend.contexts.simulation.infrastructure.response_loader import ResponseLoader, load_density_by_pvtnum
from backend.contexts.simulation.infrastructure.runner import OpmRunner, deck_hashes
from backend.contexts.simulation.infrastructure.dataset_manifest import (
    ALWAYS_RETAINED,
    COMPACTED_ON_REQUEST,
    CORES_PER_CONTAINER,
    MANIFEST_NAME,
    PLAN_NAME,
    RETAINED_RUN_SUFFIXES,
    SCHEDULES_DIR,
    DatasetBuildReport,
    DatasetManifest,
    DatasetSample,
    RunMetadata,
    SkippedScenario,
    dataset_hash,
    default_max_workers,
)

__all__ = [
    "ALWAYS_RETAINED",
    "COMPACTED_ON_REQUEST",
    "CORES_PER_CONTAINER",
    "MANIFEST_NAME",
    "PLAN_NAME",
    "RETAINED_RUN_SUFFIXES",
    "SCHEDULES_DIR",
    "DatasetBuildReport",
    "DatasetError",
    "DatasetGenerator",
    "DatasetManifest",
    "DatasetSample",
    "RunMetadata",
    "SkippedScenario",
    "dataset_hash",
    "default_max_workers",
    "schedule_keys",
]


class DatasetGenerator:
    def __init__(
        self,
        model_dir: Path | str,
        dataset_root: Path | str,
        *,
        base_schedule: Schedule | None = None,
        emitter: OpmDeckEmitter | None = None,
        runner_factory: Callable[[Path], object] | None = None,
        cache_root: Path | str | None = None,
        summary_spec: SummarySpec | None = None,
        max_workers: int | None = None,
        timeout_seconds: float | None = None,
        load_responses: bool = True,
        compact_artifacts: bool = False,
    ) -> None:
        self.model_dir = Path(model_dir).resolve()
        self.dataset_root = Path(dataset_root).resolve()
        self.dataset_root.mkdir(parents=True, exist_ok=True)
        self.emitter = emitter or OpmDeckEmitter(self.model_dir)
        self.summary_spec = summary_spec
        self.max_workers = max_workers or default_max_workers()
        self.timeout_seconds = timeout_seconds
        self.load_responses = load_responses
        self.compact_artifacts = compact_artifacts
        self.cache_root = (
            Path(cache_root).resolve()
            if cache_root is not None
            else self.dataset_root / "cache"
        )
        self.cache = RunCache(self.cache_root)
        self.manifest = DatasetManifest(self.dataset_root / MANIFEST_NAME)
        self._base_schedule = base_schedule
        self._runner_factory = runner_factory
        self._runner_lock = threading.Lock()
        self._runner: object | None = None


    def base_schedule(self) -> Schedule:
        if self._base_schedule is None:
            self._base_schedule = dataset_base_schedule(self.model_dir, self.emitter)
        return self._base_schedule

    def runner(self) -> object:
        with self._runner_lock:
            if self._runner is None:
                if self._runner_factory is not None:
                    self._runner = self._runner_factory(self.dataset_root)
                else:
                    self._runner = CachingOpmRunner(
                        OpmRunner(
                            self.dataset_root / "runs",
                            timeout_seconds=self.timeout_seconds,
                        ),
                        self.cache,
                    )
            return self._runner


    def prepare(
        self, plan: PerturbationPlan
    ) -> tuple[tuple[MaterializedSchedule, ...], tuple[SkippedScenario, ...]]:
        base = self.base_schedule()
        accepted: list[MaterializedSchedule] = []
        skipped: list[SkippedScenario] = []
        for spec in plan:
            material = materialize(base, spec)
            report = validate_static(material.schedule)
            if report.ok:
                accepted.append(material)
            else:
                skipped.append(SkippedScenario(spec=spec, report=report))
        return tuple(accepted), tuple(skipped)


    def _deck_dir(self, material: MaterializedSchedule) -> Path:
        return self.dataset_root / "decks" / material.spec.scenario_id

    def emit_deck(self, material: MaterializedSchedule) -> EmittedOpmDeck:
        destination = self._deck_dir(material)
        if destination.exists() and any(destination.iterdir()):
            shutil.rmtree(destination)
        return self.emitter.emit(
            material.schedule, destination, summary_spec=self.summary_spec
        )

    def _run_one(self, material: MaterializedSchedule) -> tuple[RunMetadata, RunResult, EmittedOpmDeck]:
        deck = self.emit_deck(material)
        hashes = deck_hashes(deck, material.schedule)
        cached = self.cache.lookup(
            hashes.deck_hash,
            hashes.canonical_schedule_hash,
            hashes.summary_hash,
        )
        result = self.runner().run(deck, material.schedule)  # type: ignore[attr-defined]
        from_cache = cached is not None and cached.run_id == result.run_id
        metadata = RunMetadata(
            scenario_id=material.spec.scenario_id,
            family=material.spec.family,
            seed=material.spec.seed,
            spec_hash=material.spec.spec_hash,
            canonical_schedule_hash=result.canonical_schedule_hash,
            deck_hash=result.deck_hash,
            summary_hash=result.summary_hash,
            run_id=result.run_id,
            status=result.status,
            unreachable_setpoint_fraction=material.unreachable_fraction,
            wallclock_seconds=result.wallclock_seconds,
            from_cache=from_cache,
            message=result.message,
        )
        return metadata, result, deck

    def schedule_dir(self) -> Path:
        return self.dataset_root / SCHEDULES_DIR

    def retain_schedule(self, scenario_id: str, deck: EmittedOpmDeck) -> Path:
        source = Path(deck.schedule_file)
        if not source.is_file():
            raise DatasetError(
                f"scenario {scenario_id}: the materialized schedule "
                f"was not found and cannot be saved: {source}"
            )
        destination_dir = self.schedule_dir()
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{scenario_id}{source.suffix}"
        shutil.copy2(source, destination)
        return destination

    def _compact_verified_response(
        self,
        result: RunResult,
        deck: EmittedOpmDeck,
        *,
        response_hash: str,
        scenario_id: str | None = None,
    ) -> RunResult:
        self.retain_schedule(scenario_id or result.run_id, deck)
        if result.status is not RunStatus.OK or len(response_hash) != 64:
            raise DatasetError(
                f"run {result.run_id}: compact is allowed only after "
                "a successful parse and a fixed response_hash"
            )
        artifacts = tuple(Path(item).resolve() for item in result.artifacts)
        required = tuple(
            path
            for path in artifacts
            if path.suffix.upper() in RETAINED_RUN_SUFFIXES
        )
        suffixes = {path.suffix.upper() for path in required}
        if suffixes != set(RETAINED_RUN_SUFFIXES) or any(
            not path.is_file() for path in required
        ):
            raise DatasetError(
                f"run {result.run_id}: the compact cache requires existing "
                f"SMSPEC and UNSMRY, found {sorted(suffixes)}"
            )

        keep = set(required)
        run_root = (self.dataset_root / "runs" / result.run_id).resolve()
        expected_runs_root = (self.dataset_root / "runs").resolve()
        if run_root.parent != expected_runs_root or not run_root.is_dir():
            raise DatasetError(f"unsafe run directory for compact: {run_root}")
        for path in sorted(
            run_root.rglob("*"), key=lambda item: len(item.parts), reverse=True
        ):
            if path.is_file() and path.resolve() not in keep:
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass

        compacted = RunResult(
            run_id=result.run_id,
            status=result.status,
            deck_hash=result.deck_hash,
            canonical_schedule_hash=result.canonical_schedule_hash,
            summary_hash=result.summary_hash,
            artifacts=tuple(str(path) for path in sorted(required)),
            wallclock_seconds=result.wallclock_seconds,
            message=result.message,
        )
        self.cache.store(compacted)

        deck_root = deck.data_file.parent.resolve()
        expected_decks_root = (self.dataset_root / "decks").resolve()
        if deck_root.parent != expected_decks_root:
            raise DatasetError(f"unsafe deck directory for compact: {deck_root}")
        if deck_root.is_dir():
            shutil.rmtree(deck_root)
        return compacted

    def build(
        self,
        plan: PerturbationPlan,
        *,
        limit: int | None = None,
    ) -> DatasetBuildReport:
        started = datetime.now(timezone.utc)
        accepted, skipped = self.prepare(plan)
        self._write_plan(plan)

        pending = list(accepted)
        if limit is not None:
            pending = pending[:limit]

        density_by_pvtnum = (
            load_density_by_pvtnum(self.model_dir) if self.load_responses else {}
        )
        loader = ResponseLoader()
        samples: list[DatasetSample] = []
        failed: list[RunMetadata] = []
        lock = threading.Lock()

        def work(material: MaterializedSchedule) -> None:
            metadata, result, deck = self._run_one(material)
            if result.status is not RunStatus.OK:
                with lock:
                    failed.append(metadata)
                self.manifest.append(metadata)
                return
            if not self.load_responses:
                with lock:
                    samples.append(
                        DatasetSample(
                            schedule=material.schedule,
                            response=None,
                            metadata=metadata,
                        )
                    )
                self.manifest.append(metadata)
                return
            response = loader.load(
                result, deck.summary_plan, material.schedule, density_by_pvtnum
            )
            if self.compact_artifacts:
                self._compact_verified_response(
                    result,
                    deck,
                    response_hash=response.response_hash,
                    scenario_id=material.spec.scenario_id,
                )
            metadata = RunMetadata(
                scenario_id=metadata.scenario_id,
                family=metadata.family,
                seed=metadata.seed,
                spec_hash=metadata.spec_hash,
                canonical_schedule_hash=metadata.canonical_schedule_hash,
                deck_hash=metadata.deck_hash,
                summary_hash=metadata.summary_hash,
                run_id=metadata.run_id,
                status=metadata.status,
                unreachable_setpoint_fraction=metadata.unreachable_setpoint_fraction,
                wallclock_seconds=metadata.wallclock_seconds,
                from_cache=metadata.from_cache,
                response_hash=response.response_hash,
                message=metadata.message,
            )
            with lock:
                samples.append(
                    DatasetSample(
                        schedule=material.schedule,
                        response=response,
                        metadata=metadata,
                    )
                )
            self.manifest.append(metadata)

        if pending:
            workers = max(1, min(self.max_workers, len(pending)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(work, item): item for item in pending}
                for future, material in futures.items():
                    error = future.exception()
                    if error is None:
                        continue
                    failed.append(
                        RunMetadata(
                            scenario_id=material.spec.scenario_id,
                            family=material.spec.family,
                            seed=material.spec.seed,
                            spec_hash=material.spec.spec_hash,
                            canonical_schedule_hash="",
                            deck_hash="",
                            summary_hash="",
                            run_id="",
                            status=RunStatus.FAILED,
                            unreachable_setpoint_fraction=material.unreachable_fraction,
                            wallclock_seconds=0.0,
                            from_cache=False,
                            message=f"the scenario was not processed: {error}",
                        )
                    )

        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        all_metadata = tuple(
            item for item in self.manifest.read() if item.status is RunStatus.OK
        )
        return DatasetBuildReport(
            dataset_hash=dataset_hash(plan, all_metadata),
            plan_hash=plan.plan_hash,
            samples=tuple(
                sorted(samples, key=lambda item: item.metadata.scenario_id)
            ),
            failed=tuple(sorted(failed, key=lambda item: item.scenario_id)),
            skipped=skipped,
            wallclock_seconds=elapsed,
        )

    def _write_plan(self, plan: PerturbationPlan) -> None:
        payload = {
            "plan_hash": plan.plan_hash,
            "seed": plan.seed,
            "n_scenarios": len(plan),
            "families": sorted(family.value for family in plan.families()),
            "scenarios": [
                {
                    "scenario_id": spec.scenario_id,
                    "family": spec.family.value,
                    "seed": spec.seed,
                    "spec_hash": spec.spec_hash,
                }
                for spec in plan
            ],
        }
        (self.dataset_root / PLAN_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def schedule_keys(samples: Sequence[DatasetSample]) -> tuple[str, ...]:
    return tuple(hash_schedule(sample.schedule) for sample in samples)
