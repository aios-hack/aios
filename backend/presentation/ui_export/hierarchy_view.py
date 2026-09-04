"""Экран «Решения → Совет» (F11, U-04) из настоящего журнала решений.

Уровни FIELD/GROUP/WELL берутся из `HierarchyTrace`, который возвращает
`policy/hierarchy.run_step` на состоянии настоящего отклика артефакта.
Синтетики здесь нет: шаг, для которого журнал не собрался, обрывает
экспорт ошибкой, а не подставляет придуманные числа.

Реестр агентов читается из `policy/agents/registry.py`: имя, уровень и
ответственность каждого агента попадают в поле `agents`, а признак
`fired` на шаге считается по записям журнала этого уровня.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from backend.core.contracts import (
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
    Role,
    RunArtifact,
)

from backend.domain.economics import ESP_CATALOG_2007
from backend.domain.policy.agents.registry import DEFAULT_REGISTRY, AgentRegistry
from backend.domain.policy.flags import RuleFlags
from backend.domain.policy.hierarchy import (
    HierarchyResult,
    Level,
    observations_by_group,
    run_step,
)
from backend.domain.policy.state import PolicyState, RuleContext, WellObservation
from backend.domain.policy.theta import default_theta
from backend.presentation.ui_export.timeline import _JSON_DIGITS

HISTORY_DECK_OFFSET: int = 146
SETPOINT_STEP_M3_PER_DAY: float = 1.0
DEFAULT_OIL_DENSITY_T_PER_M3: float = 0.86
HEADROOM: float = 1.12


def _normatives() -> NormativeSet:
    return NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)


def _round(value: float) -> float:
    rounded = round(value, _JSON_DIGITS)
    return int(rounded) if float(rounded).is_integer() else rounded


def _group_of(artifact: RunArtifact) -> dict[str, str]:
    membership: dict[str, str] = {}
    for group_id in sorted(artifact.groups.groups):
        for well in artifact.groups.groups[group_id]:
            membership.setdefault(well, group_id)
    return membership


def _rows_by_deck_index(
    artifact: RunArtifact,
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for row in artifact.state_at_date:
        rows.setdefault(row.deck_date_index, {})[row.well] = row
    return rows


def _observations(
    artifact: RunArtifact,
    rows: Mapping[int, Mapping[str, Any]],
    control_step: int,
    oil_density_t_per_m3: float,
) -> dict[str, WellObservation]:
    deck_index = HISTORY_DECK_OFFSET + control_step
    at_step = rows.get(deck_index)
    if at_step is None:
        raise ValueError(
            f"шаг {control_step}: отклика на дате дека {deck_index} нет — "
            f"журнал решений построить не на чем"
        )
    observed: dict[str, WellObservation] = {}
    for well, state in artifact.schedule.initial_state.items():
        if state.role is Role.NONE:
            continue
        row = at_step.get(well)
        if row is None:
            continue
        liquid = max(row.liquid_rate, 0.0)
        ceiling = liquid * oil_density_t_per_m3 * (1.0 - 1e-9)
        observed[well] = WellObservation(
            well=well,
            role=state.role,
            is_open=state.operating_status.name == "OPEN",
            liquid_rate_m3_per_day=liquid,
            oil_rate_t_per_day=max(0.0, min(row.oil_rate, ceiling)),
            injection_rate_m3_per_day=max(row.injection_rate, 0.0),
            setpoint_m3_per_day=state.setpoint,
        )
    if not observed:
        raise ValueError(
            f"шаг {control_step}: ни одна скважина не наблюдается в отклике — "
            f"совет некому собрать"
        )
    return observed


def _field_limit(state: PolicyState) -> float:
    return sum(
        observation.injection_rate_m3_per_day
        for observation in state.wells.values()
        if observation.role is Role.INJ
    )


def _context(
    artifact: RunArtifact,
    state: PolicyState,
    normatives: NormativeSet,
    oil_density_t_per_m3: float,
) -> RuleContext:
    by_group = observations_by_group(state, artifact.groups)
    injection: dict[str, float] = {}
    offtake: dict[str, float] = {}
    for group_id, wells in by_group.items():
        injection[group_id] = sum(
            well.injection_rate_m3_per_day
            for well in wells
            if well.role is Role.INJ and well.is_open
        )
        offtake[group_id] = sum(
            well.liquid_rate_m3_per_day
            for well in wells
            if well.role is Role.PROD and well.is_open
        )
    return RuleContext(
        normatives=normatives,
        oil_density_t_per_m3=oil_density_t_per_m3,
        constraints=artifact.constraints,
        influence=artifact.lambda_,
        groups=artifact.groups,
        group_injection_m3_per_day=injection,
        group_offtake_m3_per_day=offtake,
    )


def run_hierarchy_steps(
    artifact: RunArtifact,
    *,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    flags: RuleFlags | None = None,
    registry: AgentRegistry = DEFAULT_REGISTRY,
) -> list[tuple[PolicyState, HierarchyResult]]:
    """Настоящий прогон политики по всем шагам управления артефакта."""

    rule_flags = RuleFlags() if flags is None else flags
    theta = default_theta()
    normatives = _normatives()
    rows = _rows_by_deck_index(artifact)
    if not artifact.groups.groups:
        raise ValueError(
            "нарезка артефакта пуста: уровень участка в журнале решений "
            "не восстановим"
        )
    collected: list[tuple[PolicyState, HierarchyResult]] = []
    for control_step in range(artifact.schedule.meta.n_control_dates - 1):
        observed = _observations(artifact, rows, control_step, oil_density_t_per_m3)
        state = PolicyState(control_step=control_step, wells=observed)
        context = _context(artifact, state, normatives, oil_density_t_per_m3)
        try:
            result = run_step(
                state,
                context,
                theta,
                rule_flags,
                field_limit_m3_per_day=_field_limit(state),
                setpoint_step_m3_per_day=SETPOINT_STEP_M3_PER_DAY,
                registry=registry,
            )
        except ValueError as error:
            raise ValueError(
                f"шаг {control_step}: политика не собрала журнал решений "
                f"({error}) — синтетику вместо него экспортёр не подставляет"
            ) from error
        if not result.trace.entries:
            raise ValueError(
                f"шаг {control_step}: журнал решений пуст — показывать на "
                f"экране «Совет» нечего"
            )
        collected.append((state, result))
    if not collected:
        raise ValueError(
            "прогон политики не дал ни одного шага: журнал решений пуст"
        )
    return collected


def _agents(registry: AgentRegistry) -> list[dict[str, Any]]:
    return [
        {
            "name": agent.name,
            "level": agent.level.value,
            "responsibilities": list(agent.responsibilities),
        }
        for agent in registry.call_order()
    ]


def _field_level(result: HierarchyResult) -> dict[str, Any]:
    allocation = result.allocation
    limit = _round(allocation.field_limit_m3_per_day)
    return {
        "injection_limit_m3_per_day": limit,
        "water_available_m3_per_day": _round(
            allocation.field_limit_m3_per_day * HEADROOM
        ),
        "allocated_m3_per_day": _round(allocation.allocated_m3_per_day()),
        "allocations": [
            {
                "group": group.group_id,
                "limit_m3_per_day": _round(group.injection_m3_per_day),
                "share_of_field": _round(group.share_of_field),
                "demand_rub_per_m3": _round(group.demand_rub_per_m3),
            }
            for group in allocation.limits
        ],
    }


def _group_levels(result: HierarchyResult) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    for decision in result.group_decisions:
        allocations: dict[str, float] = {}
        for event in decision.decisions:
            if event.value is None:
                continue
            if event.kind.value != "SET_RATE":
                continue
            allocations[event.well] = event.value
        rows = [
            {"well": well, "value_m3_per_day": _round(allocations[well])}
            for well in sorted(allocations)
        ]
        levels.append(
            {
                "group": decision.group_id,
                "received_m3_per_day": _round(
                    decision.limit.injection_m3_per_day
                ),
                "requested_m3_per_day": _round(
                    decision.requested_injection_m3_per_day
                ),
                "allocations": rows,
                "trace_entries": len(decision.trace),
            }
        )
    return levels


def _well_rows(
    result: HierarchyResult, membership: Mapping[str, str]
) -> list[dict[str, Any]]:
    limit_of = {
        limit.group_id: limit.injection_m3_per_day
        for limit in result.allocation.limits
    }
    rows: list[dict[str, Any]] = []
    for leveled in result.trace.by_level(Level.WELL):
        entry = leveled.entry
        group_id = membership.get(entry.well)
        inputs = {name: _round(value) for name, value in entry.inputs.items()}
        if group_id is not None:
            inputs["group_limit_m3_per_day"] = _round(limit_of[group_id])
        rows.append(
            {
                "well": entry.well,
                "group": group_id,
                "agent": leveled.agent,
                "decision": entry.decision,
                "rule": entry.rule.value,
                "inputs": inputs,
                "constraint": _constraint_of(entry.decision, entry.inputs),
            }
        )
    rows.sort(key=lambda row: (row["well"], row["rule"]))
    return rows


def _constraint_of(decision: str, inputs: Mapping[str, float]) -> str | None:
    if decision == "VETO_OUTAGE":
        return "OUTAGE"
    requested = inputs.get("requested_value_m3_per_day")
    applied = inputs.get("applied_value_m3_per_day")
    if requested is None or applied is None:
        return None
    ceiling = inputs.get("lrat_ceiling_m3_per_day")
    if ceiling is not None and applied >= ceiling > 0.0 and requested > ceiling:
        return "LRAT_CEILING"
    if requested > 0.0 and applied <= 0.0:
        return "KNS_LIMIT"
    if applied != requested:
        return "SETPOINT_QUANTIZATION"
    return None


def build_hierarchy(
    artifact: RunArtifact,
    *,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    flags: RuleFlags | None = None,
    registry: AgentRegistry = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    membership = _group_of(artifact)
    wells = list(artifact.schedule.meta.wells)
    ungrouped = [well for well in wells if well not in membership]
    group_ids = sorted(artifact.groups.groups)
    collected = run_hierarchy_steps(
        artifact,
        oil_density_t_per_m3=oil_density_t_per_m3,
        flags=flags,
        registry=registry,
    )
    steps: list[dict[str, Any]] = []
    for state, result in collected:
        counted = result.trace.count_by_level()
        fired = {level: counted[level] > 0 for level in Level}
        steps.append(
            {
                "control_step": state.control_step,
                "field": _field_level(result),
                "groups": _group_levels(result),
                "wells": _well_rows(result, membership),
                "ungrouped": ungrouped,
                "agents_fired": [
                    agent.name
                    for agent in registry.call_order()
                    if fired[agent.level]
                ],
                "trace_entries_by_level": {
                    level.value: counted[level] for level in Level
                },
                "decisions": len(result.decisions),
            }
        )
    return {
        "n_control_dates": artifact.schedule.meta.n_control_dates,
        "groups": group_ids,
        "ungrouped": ungrouped,
        "agents": _agents(registry),
        "steps": steps,
    }


def export_hierarchy_json(
    artifact: RunArtifact,
    out_path: str | Path,
    *,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    flags: RuleFlags | None = None,
    registry: AgentRegistry = DEFAULT_REGISTRY,
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_hierarchy(
                artifact,
                oil_density_t_per_m3=oil_density_t_per_m3,
                flags=flags,
                registry=registry,
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return out
