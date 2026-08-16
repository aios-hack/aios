from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts import RunArtifact


def build_npv_by_well(artifact: RunArtifact) -> dict[str, Any]:
    table = artifact.npv_table
    wells = [
        {
            "well": well,
            "pre_tax": items.discounted_fcf + items.income_tax * items.df,
            "with_allocated_tax": items.discounted_fcf,
        }
        for well, items in sorted(table.by_well.items())
    ]
    return {
        "wells": wells,
        "total": {
            "pre_tax": sum(row["pre_tax"] for row in wells),
            "with_allocated_tax": sum(row["with_allocated_tax"] for row in wells),
        },
        "npv_methodology": table.npv_methodology,
    }


def export_npv_json(artifact: RunArtifact, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_npv_by_well(artifact), ensure_ascii=False, indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )
    return out
