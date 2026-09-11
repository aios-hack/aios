from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from backend.core.contracts import RunArtifact


def build_npv_by_well(artifact: RunArtifact) -> dict[str, Any]:
    table = artifact.npv_table
    # `by_well` spans the whole horizon, so its `df` is intentionally NaN in
    # the production economics table.  In that case the discounted field tax
    # is exact at `by_year` level and is allocated between wells pro-rata to
    # their already allocated (undiscounted) income tax.  This keeps both UI
    # columns finite and their field totals exact without inventing a single
    # horizon-wide discount factor.
    discounted_field_tax = sum(
        items.income_tax * items.df for items in table.by_year.values()
    )
    allocated_tax_total = sum(
        max(0.0, items.income_tax) for items in table.by_well.values()
    )

    def discounted_tax_for_well(items: Any) -> float:
        if math.isfinite(items.df):
            return items.income_tax * items.df
        if allocated_tax_total <= 0.0:
            return 0.0
        return discounted_field_tax * max(0.0, items.income_tax) / allocated_tax_total

    wells = [
        {
            "well": well,
            "pre_tax": items.discounted_fcf + discounted_tax_for_well(items),
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
        "pre_tax_allocation": (
            "per-well discounted tax where available; otherwise exact discounted "
            "field tax allocated pro-rata by undiscounted per-well income tax"
        ),
    }


def export_npv_json(artifact: RunArtifact, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_npv_by_well(artifact),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    return out
