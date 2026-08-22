"""Трёхуровневый совет по шагам управления для вида «Совет» (F11).

Форма повторяет `policy/hierarchy.py`: `FIELD` раздаёт лимит закачки по
участкам, `GROUP` делит полученное между своими скважинами, `WELL` несёт
решение исполнителя с правилом и сработавшим физическим ограничением.
Реальный экспорт позже собирается из `HierarchyTrace` артефакта; здесь
уровни синтезируются по образу того же типа, а суммы согласованы **в
данных** — интерфейс не пересчитывает и не проверяет их.

Согласованность выдерживается порядком действий: величины скважин
округляются до записи, а суммы участка и поля складываются уже из
округлённых чисел. Обратный порядок ломает равенство на шестом знаке.

Участки берутся из `artifact.groups` — из того же источника, что `groups`
в `ui/graph_view.py`; скважины вне нарезки перечислены в `ungrouped`
явно, а не подразумеваются вычитанием.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.contracts import Role, RunArtifact

from backend.presentation.ui_export.demo_rng import Rng
from backend.presentation.ui_export.timeline import _JSON_DIGITS

CONSTRAINTS: tuple[str, ...] = (
    "BHP_CEILING",
    "KNS_LIMIT",
    "LRAT_CEILING",
    "OUTAGE",
)
HEADROOM: float = 1.12
_CONSTRAINT_SHARE: float = 0.22
_RULE_BY_ROLE: dict[str, str] = {"INJ": "R1", "PROD": "R2"}


def _group_of(artifact: RunArtifact) -> dict[str, str]:
    membership: dict[str, str] = {}
    for group_id in sorted(artifact.groups.groups):
        for well in artifact.groups.groups[group_id]:
            membership.setdefault(well, group_id)
    return membership


def _step_of_index(artifact: RunArtifact) -> dict[int, int]:
    n_control_dates = artifact.schedule.meta.n_control_dates
    deck_axis = {row.deck_date_index for row in artifact.state_at_date}
    offset = len(deck_axis) - n_control_dates
    terminal_step = n_control_dates - 1
    mapping: dict[int, int] = {}
    for control_step in range(n_control_dates):
        index = (
            offset + control_step
            if control_step == terminal_step
            else offset + 1 + control_step
        )
        mapping[index] = control_step
    return mapping


def _rates_by_step(
    artifact: RunArtifact,
) -> tuple[dict[tuple[int, str], float], dict[tuple[int, str], float]]:
    step_of_index = _step_of_index(artifact)
    injection: dict[tuple[int, str], float] = {}
    liquid: dict[tuple[int, str], float] = {}
    for row in artifact.state_at_date:
        control_step = step_of_index.get(row.deck_date_index)
        if control_step is None:
            continue
        injection[(control_step, row.well)] = row.injection_rate
        liquid[(control_step, row.well)] = row.liquid_rate
    return injection, liquid


def _round(value: float) -> float:
    rounded = round(value, _JSON_DIGITS)
    return int(rounded) if float(rounded).is_integer() else rounded


def _decision(role: str, value: float) -> str:
    if role == "INJ":
        return f"SET_RATE {round(value, 1)}"
    return f"SET_LRAT {round(value, 1)}"


def _constraint(rng: Rng) -> str | None:
    if rng.unit() >= _CONSTRAINT_SHARE:
        return None
    index = int(rng.unit() * len(CONSTRAINTS))
    return CONSTRAINTS[min(index, len(CONSTRAINTS) - 1)]


def build_hierarchy(artifact: RunArtifact, seed: int) -> dict[str, Any]:
    meta = artifact.schedule.meta
    wells = list(meta.wells)
    membership = _group_of(artifact)
    ungrouped = [well for well in wells if well not in membership]
    group_ids = sorted(artifact.groups.groups)
    roles = {
        well: artifact.schedule.initial_state[well].role.name
        for well in wells
        if well in artifact.schedule.initial_state
    }
    injection, liquid = _rates_by_step(artifact)
    rng = Rng(seed)
    steps: list[dict[str, Any]] = []
    for control_step in range(meta.n_control_dates):
        by_group: dict[str, list[dict[str, Any]]] = {gid: [] for gid in group_ids}
        well_rows: list[dict[str, Any]] = []
        for well in wells:
            role = roles.get(well, Role.NONE.name)
            if role == Role.NONE.name:
                continue
            group_id = membership.get(well)
            rate = _round(injection.get((control_step, well), 0.0))
            flow = _round(liquid.get((control_step, well), 0.0))
            constraint = _constraint(rng)
            if group_id is not None and role == "INJ":
                by_group[group_id].append({"well": well, "value_m3_per_day": rate})
            well_rows.append(
                {
                    "well": well,
                    "group": group_id,
                    "decision": _decision(role, rate if role == "INJ" else flow),
                    "rule": _RULE_BY_ROLE[role],
                    "inputs": {
                        "injection_rate_m3_per_day": rate,
                        "liquid_rate_m3_per_day": flow,
                        "group_limit_m3_per_day": None,
                    },
                    "constraint": constraint,
                }
            )
        groups: list[dict[str, Any]] = []
        allocations: list[dict[str, Any]] = []
        received_of: dict[str, float] = {}
        for group_id in group_ids:
            received = _round(
                sum(row["value_m3_per_day"] for row in by_group[group_id])
            )
            received_of[group_id] = received
            groups.append(
                {
                    "group": group_id,
                    "received_m3_per_day": received,
                    "allocations": by_group[group_id],
                }
            )
            allocations.append({"group": group_id, "limit_m3_per_day": received})
        field_limit = _round(sum(item["limit_m3_per_day"] for item in allocations))
        for row in well_rows:
            group_id = row["group"]
            if group_id is not None:
                row["inputs"]["group_limit_m3_per_day"] = received_of[group_id]
        steps.append(
            {
                "control_step": control_step,
                "field": {
                    "injection_limit_m3_per_day": field_limit,
                    "water_available_m3_per_day": _round(field_limit * HEADROOM),
                    "allocations": allocations,
                },
                "groups": groups,
                "wells": well_rows,
                "ungrouped": ungrouped,
            }
        )
    return {
        "n_control_dates": meta.n_control_dates,
        "groups": group_ids,
        "ungrouped": ungrouped,
        "steps": steps,
    }


def export_hierarchy_json(
    artifact: RunArtifact, out_path: str | Path, seed: int
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_hierarchy(artifact, seed),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return out
