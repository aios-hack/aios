from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from contracts import (
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
from contracts.response import N_DECK_DATES
from economics import ESP_CATALOG_2007

from ui.artifact_io import dump_bundle
from ui.base_artifact import build_base_artifact, real_meta
from ui.deck import load_wellheads
from ui.demo_artifact import DEMO_PROVENANCE, DEMO_SEED, build_demo_artifact
from ui.graph_view import export_graph_json
from ui.npv_view import export_npv_json
from ui.scenarios import export_scenarios_json
from ui.timeline import export_timeline_json, export_trace_json
from ui.webdata import DEFAULT_DECK_PATH, build_wells_data

DEMO_NOTICE_RU = "Демонстрационные данные, не результат расчёта"
DEMO_NOTICE_EN = "Demonstration data, not a computed result"
BASE_ID = "base"
WHATIF_ID = "whatif-injection-cut"
DEFAULT_OUT_DIR: Path = Path(__file__).resolve().parents[1] / "frontend" / "public" / "data"
_DEFAULT_DENSITY = 860.0

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
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def _stamp_trace(path: Path, meta: dict[str, Any]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["__meta__"] = meta
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def export_scenario(
    artifact: RunArtifact, out_dir: Path, meta_by_kind: dict[str, dict[str, Any]] | None = None
) -> list[Path]:
    """`meta_by_kind` — метка по `kind` (`timeline`/`graph`/`npv`/`trace`), по умолчанию `demo_meta`."""

    meta_by_kind = meta_by_kind or {kind: demo_meta(kind) for kind in ("timeline", "graph", "npv", "trace")}
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
    return written


def build_demo(
    out_dir: str | Path = DEFAULT_OUT_DIR, deck_path: str | Path = DEFAULT_DECK_PATH
) -> list[Path]:
    """`base` — настоящий расчёт (задача G3), `whatif-injection-cut` — демо-библиотека,
    честно помеченная синтетикой (карточка G3: демонстрационный бандл сохраняется
    отдельным сценарием и остаётся помеченным)."""

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    wells = deck_scale(deck_path)
    base_result = build_base_artifact(
        _BASE_NORMATIVES, _BASE_POLICIES, model_dir=Path(deck_path).parent
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
        [base_bundle, whatif_bundle], root / "scenarios.json"
    )
    # Индекс смешанный: base — настоящий расчёт, whatif — демо. Ни DEMO_PROVENANCE,
    # ни REAL_PROVENANCE целиком файлу не подходят — provenance у каждого сценария
    # свой (config_hash/is_submitted уже в самой записи), здесь только это и сказано.
    _stamp(scenarios_path, {"provenance": "mixed", "synthetic": None, "kind": "scenarios"})
    written.extend([base_bundle, whatif_bundle, scenarios_path])
    return written


def main() -> None:
    for path in build_demo():
        print(path)


if __name__ == "__main__":
    main()
