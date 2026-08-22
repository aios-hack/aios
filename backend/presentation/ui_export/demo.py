from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from backend.core.contracts import (
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    N_CONTROL_DATES,
    NormativeSet,
    Policies,
    QuantizationPolicy,
    RunArtifact,
    Role,
    T0,
)
from backend.core.contracts.response import N_DECK_DATES
from backend.core.paths import project_root
from backend.domain.economics import ESP_CATALOG_2007

from backend.presentation.ui_export.ablation_view import export_ablation_json
from backend.presentation.ui_export.artifact_io import dump_bundle
from backend.presentation.ui_export.base_artifact import build_base_artifact, real_meta
from backend.presentation.ui_export.deck import load_wellheads
from backend.presentation.ui_export.demo_artifact import DEMO_PROVENANCE, DEMO_SEED, build_demo_artifact
from backend.presentation.ui_export.graph_view import export_graph_json
from backend.presentation.ui_export.hierarchy_view import export_hierarchy_json
from backend.presentation.ui_export.npv_view import export_npv_json
from backend.presentation.ui_export.scenarios import ScenarioRobustness, WorstRegret, export_scenarios_json
from backend.presentation.ui_export.timeline import build_timeline, build_trace, export_timeline_json, export_trace_json
from backend.presentation.ui_export.webdata import DEFAULT_DECK_PATH, build_wells_data

DEMO_NOTICE_RU = "Демонстрационные данные, не результат расчёта"
DEMO_NOTICE_EN = "Demonstration data, not a computed result"
BASE_ID = "base"
WHATIF_ID = "whatif-injection-cut"
DEFAULT_OUT_DIR: Path = project_root() / "frontend" / "public" / "data"
_DEFAULT_DENSITY = 860.0

# F8: у `base` показатели устойчивости измерены (батарея `robustness/`
# отработала на нём), заявленного числа нет — финальный тракт сдачи не
# пройден, и `final_npv` остаётся пустым. У `whatif` не измерено ничего:
# три `null` — это «не измерено», а не «ноль». Обе ветки обязаны быть в
# наборе, иначе интерфейс рендерит только одну из них.
DEMO_ROBUSTNESS: dict[str, ScenarioRobustness] = {
    BASE_ID: ScenarioRobustness(
        ood_score=0.18,
        ood_threshold=0.5,
        worst_regret=WorstRegret(
            scenario_id="holdout-outage-and-injection-cap",
            value_rub=201_000_000.0,
            part="holdout",
        ),
    ),
    WHATIF_ID: ScenarioRobustness(),
}

_BASE_NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)
_BASE_POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)


def demo_meta(kind: str) -> dict[str, Any]:
    return {
        "provenance": DEMO_PROVENANCE,
        "synthetic": True,
        "seed": DEMO_SEED,
        "kind": kind,
        "notice_ru": DEMO_NOTICE_RU,
        "notice_en": DEMO_NOTICE_EN,
    }


def deck_scale(deck_path: str | Path = DEFAULT_DECK_PATH) -> tuple[str, ...]:
    heads = load_wellheads(deck_path)
    return tuple(sorted(heads, key=lambda name: (len(name), name)))


def _stamp(path: Path, meta: dict[str, Any]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "meta" in data and isinstance(data["meta"], dict):
        data["meta"] = {**data["meta"], **meta}
    elif isinstance(data, dict):
        data["meta"] = meta
    else:
        data = {"meta": meta, "data": data}
    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _stamp_trace(path: Path, meta: dict[str, Any]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["__meta__"] = meta
    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


SCENARIO_KINDS: tuple[str, ...] = (
    "timeline",
    "graph",
    "npv",
    "trace",
    "hierarchy",
    "ablation",
)


def export_scenario(
    artifact: RunArtifact, out_dir: Path, meta_by_kind: dict[str, dict[str, Any]] | None = None
) -> list[Path]:
    """`meta_by_kind` — метка по `kind` (`SCENARIO_KINDS`), по умолчанию `demo_meta`."""

    meta_by_kind = meta_by_kind or {kind: demo_meta(kind) for kind in SCENARIO_KINDS}
    out_dir.mkdir(parents=True, exist_ok=True)
    densities = {well: _DEFAULT_DENSITY for well in artifact.schedule.meta.wells}
    written = [
        export_timeline_json(artifact, densities, out_dir / "timeline.json"),
        export_graph_json(artifact, out_dir / "graph.json"),
        export_npv_json(artifact, out_dir / "npv.json"),
    ]
    _stamp(written[0], meta_by_kind["timeline"])
    _stamp(written[1], meta_by_kind["graph"])
    _stamp(written[2], meta_by_kind["npv"])
    trace_path = export_trace_json(artifact, out_dir / "trace.json")
    _stamp_trace(trace_path, meta_by_kind["trace"])
    written.append(trace_path)
    hierarchy_path = export_hierarchy_json(
        artifact, out_dir / "hierarchy.json", DEMO_SEED
    )
    _stamp(hierarchy_path, meta_by_kind.get("hierarchy", demo_meta("hierarchy")))
    written.append(hierarchy_path)
    ablation_path = export_ablation_json(
        artifact, out_dir / "ablation.json", DEMO_SEED
    )
    _stamp(ablation_path, meta_by_kind.get("ablation", demo_meta("ablation")))
    written.append(ablation_path)
    return written


MORPH_HOLD_MS = 5000
EVENT_HOLD_MS = 4500
OPENING_HOLD_MS = 4000
TARGET_TOTAL_MS = 60_000


def _role_and_status(step: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    return {
        row["well"]: (row["role"], row["availability"], row["operating_status"])
        for row in step["wells"]
    }


def field_events(
    timeline: dict[str, Any], trace: dict[str, dict[str, list[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    """Список подтверждаемых данными событий бандла: смена доступности,
    смена роли, остановка и сработавшее правило. Кадр демо-ролика
    выбирается только отсюда — иначе интерфейс его отбросит, не найдя
    подтверждения на шаге."""

    steps = timeline["steps"]
    events: list[dict[str, Any]] = []
    previous = _role_and_status(steps[0])
    for step in steps[1:]:
        current = _role_and_status(step)
        control_step = step["control_step"]
        for well in sorted(current, key=lambda name: (len(name), name)):
            was = previous.get(well)
            now = current[well]
            if was is None or was == now:
                continue
            if was[1] != now[1] and now[1] == "AVAILABLE":
                events.append(
                    {"step": control_step, "type": "COMMISSIONED", "well": well}
                )
            if was[0] != now[0]:
                events.append(
                    {"step": control_step, "type": "ROLE_CHANGE", "well": well}
                )
            if was[2] != now[2] and now[2] == "SHUT":
                events.append({"step": control_step, "type": "SHUT", "well": well})
        previous = current
    for well in sorted(trace, key=lambda name: (len(name), name)):
        for raw_step in sorted(trace[well], key=int):
            for record in trace[well][raw_step]:
                events.append(
                    {
                        "step": int(raw_step),
                        "type": "RULE_FIRED",
                        "well": well,
                        "rule": record["rule"],
                    }
                )
    events.sort(key=lambda item: (item["step"], item["type"], item["well"]))
    return events


def _pick_spread(events: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if not events or count <= 0:
        return []
    if len(events) <= count:
        return list(events)
    stride = len(events) / count
    return [events[min(len(events) - 1, int(index * stride))] for index in range(count)]


def build_demo_script(
    timeline: dict[str, Any], trace: dict[str, dict[str, list[dict[str, Any]]]]
) -> dict[str, Any]:
    """Документ демо-ролика: кадры подтверждены содержимым бандла, суммарная
    длительность около `TARGET_TOTAL_MS`. Порядок и сцены — авторский выбор,
    сами события — нет."""

    available = field_events(timeline, trace)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in available:
        by_type.setdefault(event["type"], []).append(event)
    frames: list[dict[str, Any]] = [
        {
            "step": 0,
            "scene": "projection",
            "t": 0,
            "well": None,
            "event": None,
            "hold_ms": OPENING_HOLD_MS,
        },
        {
            "step": 0,
            "scene": "projection",
            "t": 1,
            "well": None,
            "event": {"type": "MORPH"},
            "hold_ms": MORPH_HOLD_MS,
        },
    ]
    budget = TARGET_TOTAL_MS - OPENING_HOLD_MS - MORPH_HOLD_MS
    slots = budget // EVENT_HOLD_MS
    order = ("COMMISSIONED", "ROLE_CHANGE", "SHUT", "RULE_FIRED")
    present = [name for name in order if by_type.get(name)]
    if not present:
        return {"frames": frames}
    per_type = max(1, slots // len(present))
    chosen: list[dict[str, Any]] = []
    for name in present:
        chosen.extend(_pick_spread(by_type[name], per_type))
    chosen.sort(key=lambda item: (item["step"], item["type"], item["well"]))
    scenes = ("projection", "chronomap")
    for index, event in enumerate(chosen[:slots]):
        payload: dict[str, Any] = {"type": event["type"], "well": event["well"]}
        if "rule" in event:
            payload["rule"] = event["rule"]
        frames.append(
            {
                "step": event["step"],
                "scene": scenes[index % len(scenes)],
                "well": event["well"],
                "event": payload,
                "hold_ms": EVENT_HOLD_MS,
            }
        )
    return {"frames": frames, "total_ms": sum(frame["hold_ms"] for frame in frames)}


def export_demo_script_json(
    timeline: dict[str, Any],
    trace: dict[str, dict[str, list[dict[str, Any]]]],
    out_path: str | Path,
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_demo_script(timeline, trace),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return out


def build_demo(
    out_dir: str | Path = DEFAULT_OUT_DIR,
    deck_path: str | Path = DEFAULT_DECK_PATH,
    lambda_path: str | Path | None = None,
) -> list[Path]:
    """`base` — настоящий расчёт (задача G3), `whatif-injection-cut` — демо-библиотека,
    честно помеченная синтетикой (карточка G3: демонстрационный бандл сохраняется
    отдельным сценарием и остаётся помеченным)."""

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    wells = deck_scale(deck_path)
    base_result = build_base_artifact(
        _BASE_NORMATIVES,
        _BASE_POLICIES,
        model_dir=Path(deck_path).parent,
        lambda_path=lambda_path,
    )
    base = base_result.artifact
    base_meta_by_kind = {
        kind: real_meta(kind, base_result) for kind in ("timeline", "graph", "npv", "trace")
    }
    whatif = build_demo_artifact(
        wells=wells,
        n_control_dates=N_CONTROL_DATES,
        n_deck_dates=N_DECK_DATES,
        t0=T0,
        seed=DEMO_SEED + 1,
        tag=WHATIF_ID,
    )
    written = list(export_scenario(base, root, base_meta_by_kind))
    written.extend(export_scenario(base, root / BASE_ID, base_meta_by_kind))
    written.extend(export_scenario(whatif, root / WHATIF_ID))

    wells_path = root / "wells.json"
    wells_data = build_wells_data(deck_path)
    wells_data["meta"] = demo_meta("wells-from-deck") | {
        "synthetic": False,
        "provenance": "deck",
    }
    wells_path.write_text(
        json.dumps(wells_data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    written.append(wells_path)

    bundles = root / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    base_bundle = bundles / "base.json"
    whatif_bundle = bundles / f"{WHATIF_ID}.json"
    dump_bundle(base, base_bundle)
    dump_bundle(whatif, whatif_bundle)
    scenarios_path = export_scenarios_json(
        [base_bundle, whatif_bundle], root / "scenarios.json", DEMO_ROBUSTNESS
    )
    # Индекс смешанный: base — настоящий расчёт, whatif — демо. Ни DEMO_PROVENANCE,
    # ни REAL_PROVENANCE целиком файлу не подходят — provenance у каждого сценария
    # свой (config_hash/is_submitted уже в самой записи), здесь только это и сказано.
    _stamp(scenarios_path, {"provenance": "mixed", "synthetic": None, "kind": "scenarios"})
    written.extend([base_bundle, whatif_bundle, scenarios_path])

    # Ролик рассказывает сценарий, открытый по умолчанию, — `base`. Кадры
    # берутся из его же таймлайна и трассы: событие с другого сценария
    # интерфейс не подтвердит и кадр выбросит. Пустая трасса `base` значит
    # только то, что RULE_FIRED в ролике не будет, — придумывать его нельзя.
    densities = {well: _DEFAULT_DENSITY for well in base.schedule.meta.wells}
    script_path = export_demo_script_json(
        build_timeline(base, densities),
        build_trace(base),
        root / "demo-script.json",
    )
    _stamp(script_path, demo_meta("demo-script"))
    written.append(script_path)
    return written


def main() -> None:
    # Путь к измеренной λ берётся из окружения: если кампания замера
    # (`connectivity/campaign.py`) уже отработала, витрина показывает её
    # рёбра; если нет — заглушку, помеченную `lambda_measured: false`.
    measured = os.environ.get("AIOS_LAMBDA_PATH")
    for path in build_demo(lambda_path=Path(measured) if measured else None):
        print(path)


if __name__ == "__main__":
    main()
