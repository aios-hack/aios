"""Генератор датасета «расписание → отклик». Задача 30, контракт §9.

```
PerturbationPlan → [Schedule] → validate_static == [] → мост →
  [(Schedule, StateAtDate, IntervalResponse)] + метаданные
```

Три свойства, без которых компонент бесполезен на настоящем OPM (полный
прогон Model_Z — сотни секунд, §4.7):

- **дешёвый отсев раньше дорогого.** `validate_static` (§7.1) гоняется по
  каждому сценарию до эмита дека; структурно невалидный сценарий не тратит
  прогон;
- **параллелизм.** Сценарии независимы: у каждого свой каталог дека и своя
  рабочая директория прогона, общего изменяемого состояния нет. Работает
  пул потоков — вся тяжёлая часть это `subprocess.run` докера, GIL на ней не
  держится, а каждый Flow сам многопоточный, поэтому одновременных
  контейнеров разумно держать вчетверо меньше, чем ядер;
- **возобновление.** Ключ прогона — тройка хешей §4.5, поэтому прерванная
  генерация продолжается с кеша: уже посчитанные сценарии возвращаются
  `CachingOpmRunner` без запуска симулятора, и манифест дописывается
  строкой на сценарий, а не переписывается целиком.

Датасет живёт вне git (правило 9, `.gitignore`): в репозитории только этот
код и форма манифеста. Версия датасета адресуется `dataset_hash`, входящим
в provenance (§9.2); `synthetic` в метаданных всегда `False` — здесь
настоящие прогоны, а синтетика в метрики качества не допускается (§1.1).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from contracts import (
    ResponseArtifact,
    RunResult,
    RunStatus,
    Schedule,
    SummarySpec,
    canonical_bytes,
    hash_schedule,
)
from schedule import ValidationReport, validate_static

from .cache import CachingOpmRunner, RunCache
from .dataset_plan import (
    MaterializedSchedule,
    PerturbationFamily,
    PerturbationPlan,
    PerturbationSpec,
    dataset_base_schedule,
    materialize,
)
from .opm_deck import EmittedOpmDeck, OpmDeckEmitter
from .response_loader import ResponseLoader, load_density_by_pvtnum
from .runner import OpmRunner, deck_hashes

MANIFEST_NAME = "manifest.jsonl"
PLAN_NAME = "plan.json"

# Одновременных контейнеров вчетверо меньше, чем логических ядер: каждый Flow
# внутри контейнера сам многопоточный, и запуск по контейнеру на ядро только
# отбирает потоки у решателя.
CORES_PER_CONTAINER = 4


class DatasetError(ValueError):
    """Датасет нельзя собрать однозначно из плана и базового расписания."""


def default_max_workers() -> int:
    cores = os.cpu_count() or CORES_PER_CONTAINER
    return max(1, cores // CORES_PER_CONTAINER)


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Метаданные прогона §9.2: seed, статус, доля недостижимых, флаг синтетики."""

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
                "synthetic=True в канале датасета запрещён (§9.2, §1.1): "
                "синтетические данные в метрики качества не допускаются"
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
    """Пара «расписание → отклик» плюс метаданные прогона.

    Отклик — два типа `ResponseArtifact` (§4.1.1), не один тензор: их
    перепутать на уровне типов нельзя, и датасет их не склеивает. `None`
    возможен только при `load_responses=False` — режиме, в котором прогоны
    складываются в кеш, а разбор отклика откладывается; пустой
    `ResponseArtifact` вместо `None` не подставляется, иначе несуществующий
    отклик выглядел бы как посчитанный.
    """

    schedule: Schedule
    response: ResponseArtifact | None
    metadata: RunMetadata


@dataclass(frozen=True, slots=True)
class SkippedScenario:
    """Сценарий, отсеянный `validate_static` до эмита — прогон не потрачен."""

    spec: PerturbationSpec
    report: ValidationReport


@dataclass(frozen=True, slots=True)
class DatasetBuildReport:
    """Итог партии: что посчитано, что взято из кеша, что отсеяно."""

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
    """Версия датасета — хеш плана и всех ключей прогонов, вошедших в него.

    Входит в provenance (§9.2). Порядок прогонов на хеш не влияет: ключи
    сортируются, иначе параллельная генерация давала бы разный хеш для
    одного и того же датасета.
    """

    # Множество, не список: манифест дописывается построчно, и повторный
    # вызов после возобновления кладёт по второй строке на тот же сценарий с
    # тем же ключом. Датасет от этого не меняется — значит, не должен
    # меняться и его хеш.
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
    """Манифест датасета: по строке JSON на сценарий, дописывается атомарно.

    Формат — JSONL, а не единый JSON: прерванная генерация оставляет
    корректный файл из уже записанных строк, и возобновление читает его без
    восстановления. Запись под общим замком — единственная точка, где
    параллельные прогоны встречаются.
    """

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


class DatasetGenerator:
    """Порождает расписания по плану, прогоняет их и складывает пары в датасет.

    Не переписывает мост: `OpmDeckEmitter`, `OpmRunner`, `RunCache` и
    `ResponseLoader` используются как есть. Единственное, что добавляется, —
    план эксперимента, параллельная раскладка прогонов и манифест.
    """

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

    # --- вход -----------------------------------------------------------

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

    # --- дешёвая часть: план и отсев ------------------------------------

    def prepare(
        self, plan: PerturbationPlan
    ) -> tuple[tuple[MaterializedSchedule, ...], tuple[SkippedScenario, ...]]:
        """Материализация плана и `validate_static` — без единого прогона.

        Возвращает то, что заслуживает симулятора, и то, что отсеяно (§9).
        """

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

    # --- дорогая часть: прогоны -----------------------------------------

    def _deck_dir(self, material: MaterializedSchedule) -> Path:
        return self.dataset_root / "decks" / material.spec.scenario_id

    def emit_deck(self, material: MaterializedSchedule) -> EmittedOpmDeck:
        """Свой каталог дека на сценарий — прогоны не делят изменяемых файлов."""

        destination = self._deck_dir(material)
        if destination.exists() and any(destination.iterdir()):
            shutil.rmtree(destination)
        return self.emitter.emit(
            material.schedule, destination, summary_spec=self.summary_spec
        )

    def _run_one(self, material: MaterializedSchedule) -> tuple[RunMetadata, RunResult, EmittedOpmDeck]:
        deck = self.emit_deck(material)
        hashes = deck_hashes(deck, material.schedule)
        # Попадание фиксируется до прогона: `CachingOpmRunner` возвращает
        # сохранённый `RunResult` как есть, и отличить его от свежего можно
        # только по тому, лежал ли этот `run_id` в кеше заранее.
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

    def _compact_verified_response(
        self,
        result: RunResult,
        deck: EmittedOpmDeck,
        *,
        response_hash: str,
    ) -> RunResult:
        """Retain the reloadable Summary pair after a verified parse.

        The destructive part is deliberately behind three conditions: the
        simulator run is OK, ``ResponseLoader`` has already returned, and its
        canonical response hash is present.  The cache entry is rewritten to
        the surviving SMSPEC/UNSMRY paths before the duplicated deck is
        removed.  Failed or unparsed runs are never compacted.
        """

        if result.status is not RunStatus.OK or len(response_hash) != 64:
            raise DatasetError(
                f"прогон {result.run_id}: compact разрешён только после "
                "успешного разбора и фиксации response_hash"
            )
        artifacts = tuple(Path(item).resolve() for item in result.artifacts)
        required = tuple(
            path
            for path in artifacts
            if path.suffix.upper() in {".SMSPEC", ".UNSMRY"}
        )
        suffixes = {path.suffix.upper() for path in required}
        if suffixes != {".SMSPEC", ".UNSMRY"} or any(
            not path.is_file() for path in required
        ):
            raise DatasetError(
                f"прогон {result.run_id}: compact cache требует существующие "
                f"SMSPEC и UNSMRY, найдено {sorted(suffixes)}"
            )

        keep = set(required)
        run_root = (self.dataset_root / "runs" / result.run_id).resolve()
        expected_runs_root = (self.dataset_root / "runs").resolve()
        if run_root.parent != expected_runs_root or not run_root.is_dir():
            raise DatasetError(f"небезопасный каталог прогона для compact: {run_root}")
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
            raise DatasetError(f"небезопасный каталог дека для compact: {deck_root}")
        if deck_root.is_dir():
            shutil.rmtree(deck_root)
        return compacted

    def build(
        self,
        plan: PerturbationPlan,
        *,
        limit: int | None = None,
    ) -> DatasetBuildReport:
        """Прогнать план и сложить пары в датасет. Прерванный вызов возобновляем.

        Возобновление отдельного флага не требует и не имеет: ключ прогона —
        тройка хешей (§4.5), поэтому повторный вызов на том же плане поднимает
        уже посчитанное из кеша и досчитывает только недостающее. Прерванная
        генерация продолжается тем же вызовом, каким была начата.

        `limit` режет партию — им отлаживают генератор, не намолачивая полный
        датасет.
        """

        started = datetime.now(timezone.utc)
        accepted, skipped = self.prepare(plan)
        self._write_plan(plan)

        # Возобновление держится на кеше прогонов (§4.5), а не на списке
        # сделанного: сценарий из манифеста всё равно проходит через `build`,
        # но симулятора не стоит — `CachingOpmRunner` отдаёт сохранённый
        # `RunResult`, и пара «расписание → отклик» попадает в результат.
        # Пропуск по манифесту вернул бы пустой датасет на повторном вызове:
        # прогоны есть, а пар нет.
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
                    result, deck, response_hash=response.response_hash
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
                    # Один испорченный отклик не снимает всю партию: сценарий
                    # уходит в `failed`, остальные прогоны остаются в кеше и
                    # при следующем вызове не пересчитываются.
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
                            message=f"сценарий не обработан: {error}",
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
    """`canonical_schedule_hash` каждой пары — ось адресации датасета (§2.3)."""

    return tuple(hash_schedule(sample.schedule) for sample in samples)
