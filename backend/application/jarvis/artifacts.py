from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DATA_ENV_VAR = "AIOS_UI_DATA"
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
