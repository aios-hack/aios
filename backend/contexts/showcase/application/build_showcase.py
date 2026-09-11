from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.contexts.runs.domain.run_artifact import RunArtifact
from backend.contexts.reservoir.domain.response import N_DECK_DATES
from backend.contexts.schedule.domain.schedule import N_CONTROL_DATES, T0
from backend.contexts.showcase.application.exporters.ablation_view import (
    ablation_meta,
    export_ablation_json,
)
from backend.contexts.showcase.infrastructure.artifact_io import dump_bundle
from backend.contexts.showcase.application.base_artifact import build_base_artifact, real_meta
from backend.contexts.showcase.infrastructure.synthetic_artifact import (
    DEMO_SEED,
    build_demo_artifact,
)
from backend.contexts.showcase.application.exporters.graph_view import export_graph_json
from backend.contexts.showcase.application.exporters.hierarchy_view import (
    export_hierarchy_json,
    export_hierarchy_steps,
)
from backend.contexts.showcase.application.exporters.maps_view import export_maps
from backend.contexts.showcase.application.exporters.npv_view import export_npv_json
from backend.contexts.showcase.application.scenarios import (
    ScenarioRobustness,
    export_scenarios_json,
)
from backend.contexts.showcase.application.exporters.timeline import (
    build_timeline,
    build_trace,
    export_timeline_json,
    export_trace_json,
)
from backend.contexts.showcase.application.showcase_meta import (
    BASE_ID,
    DEFAULT_OUT_DIR,
    DEMO_ROBUSTNESS,
    HIERARCHY_PROVENANCE,
    WHATIF_ID,
    _BASE_NORMATIVES,
    _BASE_POLICIES,
    _DEFAULT_DENSITY,
    _oil_densities,
    confirmed_base_robustness,
    deck_scale,
    demo_meta,
    hierarchy_meta,
)
from backend.contexts.showcase.application.showcase_script import (
    EVENT_HOLD_MS,
    MORPH_HOLD_MS,
    OPENING_HOLD_MS,
    TARGET_TOTAL_MS,
    build_demo_script,
    export_demo_script_json,
    field_events,
)
from backend.contexts.reservoir.application.well_geometry import (
    DEFAULT_DECK_PATH,
    build_wells_data,
)
from backend.shared.settings import Settings
from backend.shared.json_io import read_json


def _stamp(path: Path, meta: dict[str, Any]) -> None:
    data = read_json(path)
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
    data = read_json(path)
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
    meta_by_kind = meta_by_kind or {kind: demo_meta(kind) for kind in SCENARIO_KINDS}
    out_dir.mkdir(parents=True, exist_ok=True)
    densities = _oil_densities(artifact.schedule.meta.wells)
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
    hierarchy_path = export_hierarchy_json(artifact, out_dir / "hierarchy.json")
    _stamp(hierarchy_path, meta_by_kind.get("hierarchy", hierarchy_meta(artifact)))
    document = read_json(hierarchy_path)
    hierarchy_path.unlink()
    written.extend(export_hierarchy_steps(document, out_dir))
    ablation_path = export_ablation_json(
        artifact, out_dir / "ablation.json", DEMO_SEED
    )
    _stamp(ablation_path, meta_by_kind.get("ablation", ablation_meta()))
    written.append(ablation_path)
    return written


def build_demo(
    out_dir: str | Path = DEFAULT_OUT_DIR,
    deck_path: str | Path = DEFAULT_DECK_PATH,
    lambda_path: str | Path | None = None,
) -> list[Path]:
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
    base_robustness = confirmed_base_robustness(
        base.npv_table.npv_methodology, base_result.source_run_id
    )
    base_meta_by_kind: dict[str, dict[str, Any]] = {
        kind: real_meta(kind, base_result) for kind in ("timeline", "graph", "npv", "trace")
    }
    base_meta_by_kind["hierarchy"] = {
        **real_meta("hierarchy", base_result),
        **hierarchy_meta(base),
        "source_run_id": base_result.source_run_id,
        "response_hash": base_result.response_hash,
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

    written.append(export_maps(root / "maps", wells_path=wells_path))

    bundles = root / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    base_bundle = bundles / "base.json"
    whatif_bundle = bundles / f"{WHATIF_ID}.json"
    dump_bundle(base, base_bundle)
    dump_bundle(whatif, whatif_bundle)
    scenarios_path = export_scenarios_json(
        [base_bundle, whatif_bundle],
        root / "scenarios.json",
        {**DEMO_ROBUSTNESS, BASE_ID: base_robustness},
    )
    _stamp(scenarios_path, {"provenance": "mixed", "synthetic": None, "kind": "scenarios"})
    written.extend([base_bundle, whatif_bundle, scenarios_path])

    densities = _oil_densities(base.schedule.meta.wells)
    script_path = export_demo_script_json(
        build_timeline(base, densities),
        build_trace(base),
        root / "demo-script.json",
    )
    _stamp(script_path, demo_meta("demo-script"))
    written.append(script_path)
    return written


def main(settings: Settings | None = None) -> None:
    resolved = Settings.from_env() if settings is None else settings
    for path in build_demo(lambda_path=resolved.lambda_path):
        print(path)


if __name__ == "__main__":
    main()
