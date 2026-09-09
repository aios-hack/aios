from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DATA_ENV_VAR = "AIOS_UI_DATA"
RUNS_ENV_VAR = "AIOS_JARVIS_RUNS"
OUT_ENV_VAR = "AIOS_OUT_DIR"
MANIFEST_FILE = "manifest.json"
SUBMISSION_DIR = "submission"
CLAIMED_NPV_FILE = "claimed_npv.json"
SCHEDULE_INCLUDE_FILE = "wells_schedule.inc"
VALIDATION_DIR = "validation"
VALIDATION_RESULT_FILE = "result.json"
CONSTRAINTS_REPORT_FILE = "constraints_report.json"
NOT_RECORDED = "not-recorded"
MANIFEST_PROVENANCE_FIELDS: tuple[str, ...] = (
    "model_version",
    "npv_head_version",
    "scenario_ood_version",
    "feature_context_sha256",
    "constraints_hash",
    "deck_hash",
    "normatives_sha256",
    "opm_image",
    "git_commit",
    "seed",
    "search_strategy",
    "policy_equilibrium",
    "iterations",
    "self_consistent",
)
CLAIMED_NPV_FIELDS: tuple[str, ...] = (
    "canonical_schedule_hash",
    "content_hash_submission",
    "claimed_npv_rub",
    "source_run_id",
    "response_hash",
    "deck_hash",
    "economics_config_hash",
    "methodology_version_hash",
    "constraints_hash",
    "opm_image",
    "git_commit",
    "created_at",
)
ROOT_FILES: tuple[str, ...] = ("wells", "scenarios", "demo-script")
SCENARIO_FILES: tuple[str, ...] = (
    "timeline",
    "npv",
    "graph",
    "hierarchy",
    "ablation",
    "trace",
)
DEFAULT_SCENARIO = "base"


class ArtifactError(RuntimeError):
    pass


def default_data_root() -> Path:
    from_env = os.environ.get(DATA_ENV_VAR)
    if from_env:
        return Path(from_env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "frontend" / "public" / "data"
        if candidate.is_dir():
            return candidate
    raise ArtifactError(
        "UI data showcase not found: point at its directory with the "
        f"{DATA_ENV_VAR} environment variable, or run from the repository root "
        "that contains frontend/public/data"
    )


@dataclass(frozen=True, slots=True)
class WellSteps:
    well: str
    steps: dict[int, Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ScenarioIndex:
    scenario: str
    timeline: Mapping[str, Any]
    npv: Mapping[str, Any]
    graph: Mapping[str, Any]
    ablation: Mapping[str, Any]
    trace: Mapping[str, Any]
    hierarchy: Mapping[str, Any]
    by_well: Mapping[str, WellSteps]
    npv_by_well: Mapping[str, Mapping[str, Any]]
    edges_by_well: Mapping[str, tuple[Mapping[str, Any], ...]]
    dates: tuple[str, ...]

    def step_count(self) -> int:
        return len(self.dates)

    def require_step(self, step: int) -> Mapping[str, Any]:
        steps = self.timeline["steps"]
        if not isinstance(step, int) or step < 0 or step >= len(steps):
            raise ArtifactError(
                f"step {step} does not exist in scenario {self.scenario}: the "
                f"available steps are 0 through {len(steps) - 1}"
            )
        return steps[step]

    def require_well(self, well: str) -> WellSteps:
        found = self.by_well.get(str(well))
        if found is None:
            raise ArtifactError(
                f"well {well} is not in the stock of scenario {self.scenario}: "
                f"the showcase holds {len(self.by_well)} wells"
            )
        return found

    def step_for_date(self, date: str) -> int:
        for index, value in enumerate(self.dates):
            if value == date or value.startswith(date):
                return index
        raise ArtifactError(
            f"date {date} is outside the horizon of scenario {self.scenario}: "
            f"the horizon runs from {self.dates[0]} to {self.dates[-1]}"
        )

    def provenance(self) -> str:
        meta = self.timeline.get("meta")
        if isinstance(meta, Mapping):
            value = meta.get("provenance")
            if isinstance(value, str):
                return value
        return "unknown"


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise ArtifactError(
            f"artifact {path.name} not found at {path}: the showcase is "
            "incomplete, rebuild it with the webdata command"
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ArtifactError(
            f"artifact {path} does not parse as JSON: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise ArtifactError(f"artifact {path} is not a JSON object")
    return loaded


def _index_wells(timeline: Mapping[str, Any]) -> dict[str, WellSteps]:
    collected: dict[str, dict[int, Mapping[str, Any]]] = {}
    for step in timeline["steps"]:
        index = int(step["control_step"])
        for row in step["wells"]:
            collected.setdefault(str(row["well"]), {})[index] = row
    return {well: WellSteps(well=well, steps=rows) for well, rows in collected.items()}


def _index_edges(graph: Mapping[str, Any]) -> dict[str, tuple[Mapping[str, Any], ...]]:
    collected: dict[str, list[Mapping[str, Any]]] = {}
    for edge in graph.get("edges", ()):
        collected.setdefault(str(edge["injector"]), []).append(edge)
        collected.setdefault(str(edge["producer"]), []).append(edge)
    return {
        well: tuple(sorted(rows, key=lambda row: -float(row["weight"])))
        for well, rows in collected.items()
    }


class ArtifactStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else default_data_root()
        if not self._root.is_dir():
            raise ArtifactError(
                f"showcase directory {self._root} does not exist: check the "
                f"{DATA_ENV_VAR} environment variable"
            )
        self._cache: dict[str, tuple[float, ScenarioIndex]] = {}
        self._root_cache: dict[str, tuple[float, Mapping[str, Any]]] = {}

    @property
    def root(self) -> Path:
        return self._root

    def scenarios(self) -> tuple[str, ...]:
        listed = self.root_file("scenarios").get("scenarios", ())
        names = tuple(str(entry["id"]) for entry in listed)
        if names:
            return names
        return (DEFAULT_SCENARIO,)

    def submitted(self) -> str | None:
        value = self.root_file("scenarios").get("submitted")
        return str(value) if isinstance(value, str) else None

    def scenario_entry(self, scenario: str) -> Mapping[str, Any]:
        for entry in self.root_file("scenarios").get("scenarios", ()):
            if str(entry["id"]) == scenario:
                return entry
        raise ArtifactError(
            f"scenario {scenario} is not in the showcase: available scenarios "
            f"are {', '.join(self.scenarios())}"
        )

    def root_file(self, name: str) -> Mapping[str, Any]:
        if name not in ROOT_FILES:
            raise ArtifactError(
                f"{name} is not one of the showcase root artifacts: expected one "
                f"of {', '.join(ROOT_FILES)}"
            )
        path = self._root / f"{name}.json"
        stamp = path.stat().st_mtime if path.is_file() else 0.0
        cached = self._root_cache.get(name)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        loaded = _read_json(path)
        self._root_cache[name] = (stamp, loaded)
        return loaded

    def _scenario_dir(self, scenario: str) -> Path:
        candidate = self._root / scenario
        if candidate.is_dir():
            return candidate
        if scenario == DEFAULT_SCENARIO:
            return self._root
        raise ArtifactError(
            f"scenario directory {scenario} is missing from the showcase at "
            f"{self._root}: available scenarios are {', '.join(self.scenarios())}"
        )

    def _stamp(self, directory: Path) -> float:
        total = 0.0
        for name in SCENARIO_FILES:
            path = directory / f"{name}.json"
            if path.is_file():
                total += path.stat().st_mtime
        return total

    def scenario(self, scenario: str | None = None) -> ScenarioIndex:
        name = scenario or DEFAULT_SCENARIO
        directory = self._scenario_dir(name)
        stamp = self._stamp(directory)
        cached = self._cache.get(name)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        timeline = _read_json(directory / "timeline.json")
        npv = _read_json(directory / "npv.json")
        graph = _read_json(directory / "graph.json")
        ablation = _read_json(directory / "ablation.json")
        hierarchy = _read_json(directory / "hierarchy.json")
        trace = _read_json(directory / "trace.json")
        index = ScenarioIndex(
            scenario=name,
            timeline=timeline,
            npv=npv,
            graph=graph,
            ablation=ablation,
            trace=trace,
            hierarchy=hierarchy,
            by_well=_index_wells(timeline),
            npv_by_well={str(row["well"]): row for row in npv.get("wells", ())},
            edges_by_well=_index_edges(graph),
            dates=tuple(str(step["date"]) for step in timeline["steps"]),
        )
        self._cache[name] = (stamp, index)
        return index

    def wells_file(self) -> Mapping[str, Any]:
        return self.root_file("wells")


class RunError(RuntimeError):
    pass


def default_runs_root() -> Path:
    from_env = os.environ.get(RUNS_ENV_VAR)
    if from_env:
        return Path(from_env)
    out_dir = os.environ.get(OUT_ENV_VAR)
    if out_dir:
        return Path(out_dir) / "runs"
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "out" / "runs"
    raise RunError(
        "каталог прогонов не найден: укажите его переменной окружения "
        f"{RUNS_ENV_VAR} или запускайте из корня репозитория с out/runs"
    )


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    directory: Path
    manifest: Mapping[str, Any]
    validation: Mapping[str, Any] | None
    constraints_report: Mapping[str, Any] | None
    submission: Mapping[str, Any] | None
    schedule_include: bool

    def field(self, name: str) -> Any:
        if name not in self.manifest:
            return None
        return self.manifest[name]

    def recorded(self, name: str) -> bool:
        return self.manifest.get(name) is not None

    def documents(self) -> tuple[Mapping[str, Any], ...]:
        collected: list[Mapping[str, Any]] = [self.manifest]
        for part in (self.validation, self.constraints_report, self.submission):
            if part is not None:
                collected.append(part)
        return tuple(collected)


def _read_optional_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RunError(
            f"артефакт {path} не разбирается как JSON: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise RunError(f"артефакт {path} не является объектом JSON")
    return loaded


class RunStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else default_runs_root()

    @property
    def root(self) -> Path:
        return self._root

    def exists(self) -> bool:
        return self._root.is_dir()

    def run_ids(self) -> tuple[str, ...]:
        if not self._root.is_dir():
            return ()
        found = [
            entry.name
            for entry in self._root.iterdir()
            if entry.is_dir() and (entry / MANIFEST_FILE).is_file()
        ]
        return tuple(sorted(found))

    def latest_run_id(self) -> str | None:
        if not self._root.is_dir():
            return None
        stamped: list[tuple[float, str]] = []
        for name in self.run_ids():
            path = self._root / name / MANIFEST_FILE
            stamped.append((path.stat().st_mtime, name))
        if not stamped:
            return None
        stamped.sort()
        return stamped[-1][1]

    def read(self, run_id: str | None = None) -> RunRecord:
        name = run_id if run_id is not None else self.latest_run_id()
        if name is None:
            raise RunError(
                "в каталоге прогонов нет ни одного прогона с манифестом: "
                f"{self._root}; расчёт ещё не запускался"
            )
        if Path(name).name != name:
            raise RunError(
                f"идентификатор прогона {name!r} не является именем каталога"
            )
        directory = self._root / name
        manifest_path = directory / MANIFEST_FILE
        if not manifest_path.is_file():
            known = self.run_ids()
            listed = ", ".join(known) if known else "ни одного"
            raise RunError(
                f"прогон {name!r} не найден в {self._root}: манифест "
                f"{manifest_path} отсутствует; известные прогоны — {listed}"
            )
        manifest = _read_optional_json(manifest_path)
        if manifest is None:
            raise RunError(f"манифест прогона {name!r} не читается: {manifest_path}")
        submission_dir = directory / SUBMISSION_DIR
        return RunRecord(
            run_id=name,
            directory=directory,
            manifest=manifest,
            validation=_read_optional_json(
                directory / VALIDATION_DIR / VALIDATION_RESULT_FILE
            ),
            constraints_report=_read_optional_json(
                directory / VALIDATION_DIR / CONSTRAINTS_REPORT_FILE
            ),
            submission=_read_optional_json(submission_dir / CLAIMED_NPV_FILE),
            schedule_include=(submission_dir / SCHEDULE_INCLUDE_FILE).is_file(),
        )
