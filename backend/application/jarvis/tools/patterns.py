from __future__ import annotations

from typing import Any, Mapping

from backend.core.contracts import ActiveControlMode, StateAtDate

from backend.application.jarvis.artifacts import ArtifactError, ScenarioIndex
from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure
from backend.application.jarvis.tools.labels import title
from backend.infrastructure.llm.diagnostics import (
    Finding,
    PATTERNS,
    detect_pressure_drop_at_high_rates,
)

BHP_DROP_MIN = 20.0
LIQUID_RATE_MIN = 60.0
WCT_DELTA_MIN = 0.15
LIQUID_DELTA_MAX = 0.0
INJECTION_MIN = 100.0
WINDOW_STEPS = 6
DEFAULT_LIMIT = 10
SUPPORTED: tuple[str, ...] = (
    "pressure_drop_at_high_rates",
    "wct_rise_without_oil",
    "injection_without_response",
)


def _state_rows(index: ScenarioIndex, well: str | None) -> list[StateAtDate]:
    rows: list[StateAtDate] = []
    for position, step in enumerate(index.timeline["steps"]):
        for row in step["wells"]:
            name = str(row["well"])
            if well is not None and name != well:
                continue
            rows.append(
                StateAtDate(
                    deck_date_index=position,
                    well=name,
                    liquid_rate=float(row["liquid_rate"]),
                    oil_rate=0.0,
                    injection_rate=float(row["injection_rate"]),
                    thp=0.0,
                    bhp=float(row["bhp"]),
                    well_efficiency=1.0,
                    active_control_mode=ActiveControlMode.UNKNOWN,
                )
            )
    return rows


def _watercut_rise(index: ScenarioIndex, well: str | None) -> list[Finding]:
    steps = index.timeline["steps"]
    previous: dict[str, dict[str, Any]] = {}
    findings: list[Finding] = []
    for position, step in enumerate(steps):
        current: dict[str, dict[str, Any]] = {}
        for row in step["wells"]:
            name = str(row["well"])
            current[name] = row
            if well is not None and name != well:
                continue
            before = previous.get(name)
            if before is None:
                continue
            if row["watercut"] is None or before["watercut"] is None:
                continue
            wct_delta = float(row["watercut"]) - float(before["watercut"])
            liquid_delta = float(row["liquid_rate"]) - float(before["liquid_rate"])
            if wct_delta >= WCT_DELTA_MIN and liquid_delta <= LIQUID_DELTA_MAX:
                findings.append(
                    Finding(
                        pattern_id="wct_rise_without_oil",
                        name_ru=PATTERNS["wct_rise_without_oil"],
                        well=name,
                        severity="warning",
                        inputs={
                            "watercut_prev": float(before["watercut"]),
                            "watercut_curr": float(row["watercut"]),
                            "liquid_delta": liquid_delta,
                        },
                        control_step=position,
                    )
                )
        previous = current
    return findings


def _injection_without_response(
    index: ScenarioIndex, well: str | None
) -> list[Finding]:
    steps = index.timeline["steps"]
    by_well: dict[str, list[tuple[int, float, float]]] = {}
    for position, step in enumerate(steps):
        production = float(step["field"]["production"] or 0.0)
        for row in step["wells"]:
            name = str(row["well"])
            if well is not None and name != well:
                continue
            if str(row["role"]) != "INJ":
                continue
            by_well.setdefault(name, []).append(
                (position, float(row["injection_rate"]), production)
            )
    findings: list[Finding] = []
    for name, rows in by_well.items():
        for start in range(0, len(rows) - WINDOW_STEPS + 1):
            window = rows[start : start + WINDOW_STEPS]
            if window[-1][0] - window[0][0] != WINDOW_STEPS - 1:
                continue
            injection_total = sum(value for _, value, _ in window)
            production_delta = window[-1][2] - window[0][2]
            if injection_total >= INJECTION_MIN and production_delta <= 0.0:
                findings.append(
                    Finding(
                        pattern_id="injection_without_response",
                        name_ru=PATTERNS["injection_without_response"],
                        well=name,
                        severity="warning",
                        inputs={
                            "injection_total": injection_total,
                            "production_delta": production_delta,
                        },
                        window=(window[0][0], window[-1][0]),
                    )
                )
                break
    return findings


def _as_payload(index: ScenarioIndex, finding: Finding) -> dict[str, Any]:
    window = list(finding.window) if finding.window is not None else None
    return {
        "pattern_id": finding.pattern_id,
        "name": finding.name_ru,
        "well": finding.well,
        "severity": finding.severity,
        "step": finding.control_step,
        "date": (
            index.dates[finding.control_step]
            if finding.control_step is not None
            and finding.control_step < len(index.dates)
            else None
        ),
        "window": window,
        "inputs": dict(finding.inputs),
    }


def find_patterns(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    well = arguments.get("well")
    well = str(well) if well is not None else None
    pattern = arguments.get("pattern")
    limit = int(arguments.get("limit") or DEFAULT_LIMIT)
    if pattern is not None and str(pattern) not in SUPPORTED:
        raise ToolFailure(
            f"pattern {pattern} cannot be detected from the UI showcase: the "
            f"showcase supports {', '.join(SUPPORTED)}"
        )
    try:
        index = context.index()
        if well is not None:
            index.require_well(well)
    except ArtifactError as error:
        raise ToolFailure(str(error)) from error
    findings: list[Finding] = []
    findings.extend(
        detect_pressure_drop_at_high_rates(
            _state_rows(index, well), BHP_DROP_MIN, LIQUID_RATE_MIN
        )
    )
    findings.extend(_watercut_rise(index, well))
    findings.extend(_injection_without_response(index, well))
    if pattern is not None:
        findings = [item for item in findings if item.pattern_id == str(pattern)]
    if not findings:
        raise ToolFailure(
            "the detectors found no anomaly"
            + (f" for well {well}" if well else " across the field")
            + f" in scenario {index.scenario}: there is nothing to show"
        )
    findings.sort(key=lambda item: (item.severity != "warning", item.well))
    rows = [_as_payload(index, item) for item in findings[:limit]]
    return Card(
        type="pattern",
        title=(
            title("patterns_well", context.lang, well=well)
            if well
            else title("patterns_field", context.lang)
        ),
        payload={"total": len(findings), "patterns": rows},
        provenance=index.provenance(),
    )
