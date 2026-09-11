from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from backend.contexts.assistant.infrastructure.artifacts import RunError, RunRecord
from backend.contexts.assistant.infrastructure.system_map import (
    SystemMap,
    SystemMapError,
    shared_system_map,
)
from backend.contexts.assistant.application.tools.context import Card, ToolContext, ToolFailure
from backend.contexts.assistant.application.tools.patterns import find_patterns
from backend.shared.settings import Settings
from backend.shared.paths import repository_root

PROVENANCE_KNOWLEDGE = "knowledge"
PROVENANCE_RUNS = "runs"
CHAMPION_FILE = "config/opm-champion.json"
ALERT_LIMIT = 3
NOT_RECORDED = "not-recorded"
TITLES: Mapping[str, Mapping[str, str]] = {
    "map_all": {"ru": "Карта системы AIOS", "en": "The AIOS system map"},
    "map_focus": {"ru": "Карта системы: {label}", "en": "System map: {label}"},
    "status": {"ru": "Состояние системы", "en": "System status"},
}


def _pick(key: str, lang: str, **values: object) -> str:
    entry = TITLES.get(key, {})
    template = entry.get(lang, entry.get("ru", key))
    return template.format(**values)


def _map(context: ToolContext) -> SystemMap:
    if context.system is not None:
        return context.system
    try:
        return shared_system_map()
    except SystemMapError as error:
        raise ToolFailure(str(error)) from error


def system_map(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    carte = _map(context)
    lang = context.lang
    requested = arguments.get("focus")
    focus_id: str | None = None
    if requested is not None:
        node = carte.find(str(requested))
        if node is None:
            known = ", ".join(sorted(item.id for item in carte.nodes()))
            raise ToolFailure(
                f"узла {requested!r} нет в карте системы: известные узлы — "
                f"{known}; выдумывать компоненты платформы нельзя"
            )
        focus_id = node.id
    depth = arguments.get("depth")
    try:
        nodes, edges = carte.neighbourhood(
            focus_id, int(depth) if isinstance(depth, (int, float)) else 1
        )
    except SystemMapError as error:
        raise ToolFailure(str(error)) from error
    payload: dict[str, Any] = {
        "focus": focus_id,
        "nodes": [node.as_dict() for node in nodes],
        "edges": [edge.as_dict() for edge in edges],
        "source": carte.source,
        "total_nodes": carte.node_count,
        "total_edges": carte.edge_count,
    }
    if focus_id is None:
        title = _pick("map_all", lang)
    else:
        node = carte.node(focus_id)
        label = (
            node.label.get(lang, node.label.get("ru", focus_id))
            if node is not None
            else focus_id
        )
        title = _pick("map_focus", lang, label=label)
    return Card(
        type="system-map",
        title=title,
        payload=payload,
        provenance=PROVENANCE_KNOWLEDGE,
    )


def _repository_root() -> Path:
    return repository_root(Path.cwd())


def _champion() -> dict[str, Any]:
    override = Settings.from_env().jarvis_champion
    path = override if override is not None else _repository_root() / CHAMPION_FILE
    if not path.is_file():
        return {
            "recorded": False,
            "reason": (
                f"файла чемпиона {path} нет: закреплённого лучшего прогона "
                "OPM не записано"
            ),
        }
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return {"recorded": False, "reason": f"файл чемпиона {path} не читается: {error}"}
    if not isinstance(loaded, dict):
        return {"recorded": False, "reason": f"файл чемпиона {path} не объект JSON"}
    water = loaded.get("water") or {}
    return {
        "recorded": True,
        "schedule_hash": loaded.get("canonical_schedule_hash"),
        "opm_npv_rub": loaded.get("opm_npv_rub"),
        "surrogate_npv_rub": loaded.get("raw_surrogate_npv_rub"),
        "calibrated_npv_rub": loaded.get("active_calibrated_npv_rub"),
        "sound": loaded.get("sound"),
        "ood_score": loaded.get("economic_ood_score"),
        "ood_threshold": loaded.get("economic_ood_threshold"),
        "blocking_violations": water.get("blocking_violations"),
        "source": str(path),
        "reason": None,
    }


def _last_run(context: ToolContext) -> dict[str, Any]:
    try:
        store = context.run_store()
    except ToolFailure as error:
        return {"recorded": False, "reason": str(error)}
    try:
        record: RunRecord = store.read()
    except RunError as error:
        return {"recorded": False, "reason": str(error)}
    validation = record.validation or {}
    return {
        "recorded": True,
        "run_id": record.run_id,
        "status": record.manifest.get("status"),
        "predicted_npv": record.manifest.get("predicted_npv"),
        "verified_npv": record.manifest.get("verified_npv"),
        "sound": record.manifest.get("sound"),
        "opm_status": validation.get("opm_status"),
        "dynamic_violations": validation.get("dynamic_violations"),
        "blocking_dynamic_violations": validation.get("blocking_dynamic_violations"),
        "has_submission": record.submission is not None,
        "source": str(record.directory / "manifest.json"),
        "reason": None,
    }


def _alerts(context: ToolContext) -> list[dict[str, Any]]:
    try:
        card = find_patterns(context, {"limit": ALERT_LIMIT})
    except Exception:
        return []
    rows = card.payload.get("patterns") or ()
    collected: list[dict[str, Any]] = []
    for row in rows[:ALERT_LIMIT]:
        collected.append(
            {
                "pattern": row.get("pattern_id") or row.get("name"),
                "name": row.get("name"),
                "well": row.get("well"),
                "severity": row.get("severity"),
                "step": row.get("step"),
            }
        )
    return collected


def system_status(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    index = context.index()
    step = context.resolve_step(None)
    payload: dict[str, Any] = {
        "champion": _champion(),
        "last_run": _last_run(context),
        "scenario": context.scenario_name,
        "scenarios": list(context.store.scenarios()),
        "submitted": context.store.submitted(),
        "step": step,
        "date": index.dates[step] if step < len(index.dates) else None,
        "steps": index.step_count(),
        "data": index.provenance(),
        "alerts": _alerts(context),
        "not_recorded_marker": NOT_RECORDED,
    }
    return Card(
        type="status-board",
        title=_pick("status", context.lang),
        payload=payload,
        provenance=PROVENANCE_RUNS,
    )
