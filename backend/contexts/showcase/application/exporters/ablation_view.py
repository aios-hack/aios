from __future__ import annotations

from backend.contexts.showcase.application.notices import (
    notice_fields,
)

import json
from pathlib import Path
from typing import Any

from backend.core.contracts import Rule, RunArtifact

from backend.contexts.showcase.application.exporters.timeline import _JSON_DIGITS

UPLIFT_NOT_MEASURED = "UPLIFT_NOT_MEASURED"
ABLATION_NOT_RUN = "ABLATION_NOT_RUN"

DISABLED_RULES: dict[str, str] = {"R7": UPLIFT_NOT_MEASURED}

ABLATION_PROVENANCE = "ablation-not-run"
ABLATION_NOTICE_RU = (
    "Абляция не запускалась: вклад правил в ЧДД не измерен. Показан только "
    "факт включения правила, денежных величин в файле нет"
)
ABLATION_NOTICE_EN = (
    "No ablation was run: the NPV contribution of each rule is not measured. "
    "Only the enabled flag is reported, the file carries no money values"
)


def ablation_meta() -> dict[str, Any]:
    return {
        "provenance": ABLATION_PROVENANCE,
        "synthetic": False,
        "kind": "ablation",
        "uplift_measured": False,
        "uplift_reason": ABLATION_NOT_RUN,
        **notice_fields("showcase.notice.ablation_absent"),
    }


def _round(value: float) -> float:
    rounded = round(value, _JSON_DIGITS)
    return int(rounded) if float(rounded).is_integer() else rounded


def build_ablation(artifact: RunArtifact, seed: int) -> dict[str, Any]:
    npv_total = artifact.npv_table.npv_methodology
    rules: list[dict[str, Any]] = []
    for rule in sorted(Rule, key=lambda item: item.value):
        name = rule.value
        row: dict[str, Any] = {
            "rule": name,
            "enabled": name not in DISABLED_RULES,
            "delta_npv": None,
            "share": None,
            "delta_npv_status": ABLATION_NOT_RUN,
        }
        if name in DISABLED_RULES:
            row["disabled_reason"] = DISABLED_RULES[name]
        rules.append(row)
    return {
        "npv_total": _round(npv_total),
        "rules": rules,
        "uplift_measured": False,
        "uplift_reason": ABLATION_NOT_RUN,
        "meta": ablation_meta(),
    }


def export_ablation_json(
    artifact: RunArtifact, out_path: str | Path, seed: int
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_ablation(artifact, seed),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return out
