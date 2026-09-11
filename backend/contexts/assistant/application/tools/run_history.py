from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.contexts.assistant.infrastructure.artifacts import MANIFEST_FILE, RunError, RunRecord
from backend.contexts.assistant.application.tools.context import Card, ToolContext, ToolFailure
from backend.shared.settings import Settings
from backend.shared.paths import repository_root

WEB_RUNS_ENV_VAR = "AIOS_JARVIS_WEB_RUNS"
DEFAULT_LIMIT = 6
MAX_LIMIT = 10
PROVENANCE = "runs"
NO_RUNS = "no-runs"
NO_COMPARISON = "no-comparison"
COMPARISON_FILE = "comparison.json"
PHYSICS_PREFIX = "physics"
VALIDATION_DIR = "validation"
TITLES: Mapping[str, Mapping[str, str]] = {
    "list": {"ru": "Прогоны расчёта", "en": "Calculation runs"},
    "detail": {"ru": "Прогон {run_id}", "en": "Run {run_id}"},
    "compare": {"ru": "{a} против {b}", "en": "{a} versus {b}"},
    "physics": {"ru": "Физика прогона {run_id}", "en": "Physics of run {run_id}"},
}


def _title(key: str, lang: str, **values: object) -> str:
    entry = TITLES.get(key, {})
    return entry.get(lang, entry.get("ru", key)).format(**values)


def _repository_root() -> Path:
    return repository_root(Path.cwd())


def _web_runs_root(settings: Settings | None = None) -> Path:
    resolved = Settings.from_env() if settings is None else settings
    if resolved.jarvis_web_runs is not None:
        return resolved.jarvis_web_runs
    base = resolved.out_root if resolved.raw.get("AIOS_OUT_DIR") else _repository_root() / "out"
    return base / "web-runs"


@dataclass(frozen=True, slots=True)
class Located:
    run_id: str
    directory: Path
    manifest: Mapping[str, Any]
    mtime: float


def _read_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _scan(root: Path) -> list[Located]:
    if not root.is_dir():
        return []
    found: list[Located] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        path = entry / MANIFEST_FILE
        manifest = _read_json(path)
        if manifest is None:
            continue
        found.append(
            Located(
                run_id=entry.name,
                directory=entry,
                manifest=manifest,
                mtime=path.stat().st_mtime,
            )
        )
    return found


def _roots(context: ToolContext) -> list[Path]:
    collected: list[Path] = []
    try:
        collected.append(context.run_store().root)
    except ToolFailure:
        pass
    web = _web_runs_root()
    if web not in collected:
        collected.append(web)
    return collected


def _located(context: ToolContext) -> list[Located]:
    found: list[Located] = []
    seen: set[str] = set()
    for root in _roots(context):
        for item in _scan(root):
            if item.run_id in seen:
                continue
            seen.add(item.run_id)
            found.append(item)
    found.sort(key=lambda item: (-item.mtime, item.run_id))
    return found


def _stamp(value: float) -> str:
    return (
        datetime.fromtimestamp(value, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _find(context: ToolContext, run_id: str | None) -> Located:
    items = _located(context)
    if not items:
        roots = ", ".join(str(root) for root in _roots(context))
        raise ToolFailure(
            f"{NO_RUNS}: no run with a manifest was found in the directories "
            f"{roots}; no calculation has been made yet, and its result cannot be invented"
        )
    if run_id is None:
        return items[0]
    for item in items:
        if item.run_id == run_id:
            return item
    known = ", ".join(item.run_id for item in items[:MAX_LIMIT])
    raise ToolFailure(
        f"run {run_id!r} is in none of the run directories: known runs "
        f"are {known}"
    )


def _row(item: Located) -> dict[str, Any]:
    validation = _read_json(item.directory / VALIDATION_DIR / "result.json") or {}
    provenance = _read_json(item.directory / "provenance.json") or {}
    return {
        "run_id": item.run_id,
        "ts": _stamp(item.mtime),
        "status": item.manifest.get("status"),
        "predicted_npv": item.manifest.get("predicted_npv"),
        "verified_npv": item.manifest.get("verified_npv"),
        "sound": item.manifest.get("sound"),
        "schedule_hash": item.manifest.get("schedule_hash"),
        "strategy": item.manifest.get("search_strategy")
        or provenance.get("search_strategy"),
        "seed": item.manifest.get("seed") or provenance.get("seed"),
        "opm_status": validation.get("opm_status"),
        "source": str(item.directory),
    }


def run_history(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    requested = arguments.get("limit")
    limit = int(requested) if isinstance(requested, (int, float)) else DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))
    status = arguments.get("status")
    items = _located(context)
    if not items:
        roots = ", ".join(str(root) for root in _roots(context))
        raise ToolFailure(
            f"{NO_RUNS}: no run with a manifest was found in the directories "
            f"{roots}; there is no list of runs"
        )
    rows = [_row(item) for item in items]
    if status is not None:
        wanted = str(status)
        rows = [row for row in rows if row["status"] == wanted]
        if not rows:
            statuses = sorted(
                {str(row["status"]) for row in (_row(item) for item in items)}
            )
            raise ToolFailure(
                f"there are no runs with status {wanted!r}: the statuses present "
                f"are {', '.join(statuses)}"
            )
    payload = {
        "rows": rows[:limit],
        "total": len(items),
        "status": str(status) if status is not None else None,
        "roots": [str(root) for root in _roots(context)],
    }
    return Card(
        type="run-list",
        title=_title("list", context.lang),
        payload=payload,
        provenance=PROVENANCE,
    )


def _physics_files(directory: Path) -> list[Path]:
    folder = directory / VALIDATION_DIR
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.glob("*.json")
        if path.stem.startswith(PHYSICS_PREFIX)
    )


def _physics(directory: Path) -> dict[str, Any]:
    files = _physics_files(directory)
    if not files:
        return {
            "recorded": False,
            "admissible": None,
            "checks": [],
            "blocking": None,
            "warnings": None,
            "reason": (
                "there is no physics report: the directory "
                f"{directory / VALIDATION_DIR} holds no physics*.json file, so "
                "the admissibility of the response is unknown"
            ),
            "source": None,
        }
    loaded = _read_json(files[0]) or {}
    raw_checks = loaded.get("checks") or loaded.get("invariants") or ()
    checks: list[dict[str, Any]] = []
    for entry in raw_checks:
        if not isinstance(entry, Mapping):
            continue
        checks.append(
            {
                "id": entry.get("id") or entry.get("kind") or entry.get("name"),
                "status": entry.get("status") or entry.get("severity"),
                "detail": entry.get("detail") or entry.get("message"),
            }
        )
    blocking = sum(1 for row in checks if row["status"] == "blocking")
    warnings = sum(1 for row in checks if row["status"] == "warning")
    return {
        "recorded": True,
        "admissible": loaded.get("admissible"),
        "checks": checks,
        "blocking": blocking,
        "warnings": warnings,
        "reason": None,
        "source": str(files[0]),
    }


def _detail(context: ToolContext, item: Located) -> dict[str, Any]:
    validation = _read_json(item.directory / VALIDATION_DIR / "result.json")
    constraints = _read_json(
        item.directory / VALIDATION_DIR / "constraints_report.json"
    )
    submission = _read_json(item.directory / "submission" / "claimed_npv.json")
    provenance = _read_json(item.directory / "provenance.json") or {}
    violations: list[dict[str, Any]] = []
    if validation is not None:
        for name in validation.get("failed_identities", ()) or ():
            violations.append({"kind": "identity", "detail": str(name)})
    return {
        "run_id": item.run_id,
        "ts": _stamp(item.mtime),
        "status": item.manifest.get("status"),
        "predicted_npv": item.manifest.get("predicted_npv"),
        "verified_npv": item.manifest.get("verified_npv"),
        "sound": item.manifest.get("sound"),
        "schedule_hash": item.manifest.get("schedule_hash"),
        "provenance": dict(provenance),
        "validation": dict(validation) if validation is not None else None,
        "constraints_report": dict(constraints) if constraints is not None else None,
        "claimed_npv_rub": (
            submission.get("claimed_npv_rub") if submission is not None else None
        ),
        "has_submission": submission is not None,
        "violations": violations,
        "physics": _physics(item.directory),
        "source": str(item.directory / MANIFEST_FILE),
    }


def run_detail(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    requested = arguments.get("run_id")
    item = _find(context, str(requested) if requested is not None else None)
    return Card(
        type="run",
        title=_title("detail", context.lang, run_id=item.run_id),
        payload=_detail(context, item),
        provenance=PROVENANCE,
    )


def physics_report(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    requested = arguments.get("run_id")
    item = _find(context, str(requested) if requested is not None else None)
    report = _physics(item.directory)
    if not report["recorded"]:
        raise ToolFailure(
            f"{report['reason']} (run {item.run_id})"
        )
    payload = {
        "run_id": item.run_id,
        "admissible": report["admissible"],
        "checks": report["checks"],
        "blocking": report["blocking"],
        "warnings": report["warnings"],
        "source": report["source"],
    }
    return Card(
        type="physics",
        title=_title("physics", context.lang, run_id=item.run_id),
        payload=payload,
        provenance=PROVENANCE,
    )


def _side(item: Located, context: ToolContext) -> dict[str, Any]:
    detail = _detail(context, item)
    physics = detail["physics"]
    return {
        "id": item.run_id,
        "npv": detail["verified_npv"]
        if detail["verified_npv"] is not None
        else detail["predicted_npv"],
        "predicted_npv": detail["predicted_npv"],
        "verified_npv": detail["verified_npv"],
        "status": {
            "status": detail["status"],
            "sound": detail["sound"],
            "has_submission": detail["has_submission"],
            "opm_status": (detail["validation"] or {}).get("opm_status"),
            "physics_admissible": physics["admissible"],
        },
        "constraints": {
            "recorded": detail["constraints_report"] is not None,
            "checks": (detail["constraints_report"] or {}).get("checks"),
            "dynamic_violations": (detail["validation"] or {}).get(
                "dynamic_violations"
            ),
            "blocking_dynamic_violations": (detail["validation"] or {}).get(
                "blocking_dynamic_violations"
            ),
        },
    }


def compare_runs(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    items = _located(context)
    if len(items) < 2 and (arguments.get("a") is None or arguments.get("b") is None):
        raise ToolFailure(
            f"{NO_RUNS}: a comparison needs two runs, but {len(items)} was "
            "found; there is nothing to compare"
        )
    left_id = arguments.get("a")
    right_id = arguments.get("b")
    left = _find(context, str(left_id) if left_id is not None else items[1].run_id)
    right = _find(context, str(right_id) if right_id is not None else items[0].run_id)
    if left.run_id == right.run_id:
        raise ToolFailure(
            f"run {left.run_id} is being compared with itself: the difference "
            "is always zero, name two different runs"
        )
    a = _side(left, context)
    b = _side(right, context)
    comparison = _read_json(right.directory / COMPARISON_FILE)
    delta = None
    if isinstance(a["npv"], (int, float)) and isinstance(b["npv"], (int, float)):
        delta = float(b["npv"]) - float(a["npv"])
    payload = {
        "a": a,
        "b": b,
        "delta_npv": delta,
        "top_diff_wells": (comparison or {}).get("top_diff_wells") or [],
        "comparison": dict(comparison) if comparison is not None else None,
        "comparison_reason": (
            None
            if comparison is not None
            else (
                f"{NO_COMPARISON}: run {right.run_id} has no "
                f"{COMPARISON_FILE} file, so the breakdown of the difference "
                "by well is unknown"
            )
        ),
    }
    return Card(
        type="compare",
        title=_title("compare", context.lang, a=left.run_id, b=right.run_id),
        payload=payload,
        provenance=PROVENANCE,
    )


def latest_run(context: ToolContext) -> RunRecord | None:
    try:
        return context.run_store().read()
    except (ToolFailure, RunError):
        return None
