from __future__ import annotations

from backend.contexts.showcase.application.build_showcase import (
    BASE_ID,
    DEFAULT_OUT_DIR,
    DEMO_NOTICE_EN,
    DEMO_NOTICE_RU,
    DEMO_ROBUSTNESS,
    EVENT_HOLD_MS,
    HIERARCHY_NOTICE_EN,
    HIERARCHY_NOTICE_RU,
    HIERARCHY_PROVENANCE,
    MORPH_HOLD_MS,
    OPENING_HOLD_MS,
    SCENARIO_KINDS,
    TARGET_TOTAL_MS,
    WHATIF_ID,
    build_demo,
    build_demo_script,
    confirmed_base_robustness,
    deck_scale,
    demo_meta,
    export_demo_script_json,
    export_scenario,
    field_events,
    hierarchy_meta,
    main,
)


if __name__ == "__main__":
    from backend.contexts.showcase.application.build_showcase import main as _main
    from backend.interfaces.cli.runner import run as _run

    raise SystemExit(_run(_main))


__all__ = [
    "BASE_ID",
    "DEFAULT_OUT_DIR",
    "DEMO_NOTICE_EN",
    "DEMO_NOTICE_RU",
    "DEMO_ROBUSTNESS",
    "EVENT_HOLD_MS",
    "HIERARCHY_NOTICE_EN",
    "HIERARCHY_NOTICE_RU",
    "HIERARCHY_PROVENANCE",
    "MORPH_HOLD_MS",
    "OPENING_HOLD_MS",
    "SCENARIO_KINDS",
    "TARGET_TOTAL_MS",
    "WHATIF_ID",
    "build_demo",
    "build_demo_script",
    "confirmed_base_robustness",
    "deck_scale",
    "demo_meta",
    "export_demo_script_json",
    "export_scenario",
    "field_events",
    "hierarchy_meta",
    "main",
]
