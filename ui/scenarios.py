from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts import Constraints, WellOutage

from ui.artifact_io import load_bundle

YEAR_SECTIONS: tuple[str, ...] = (
    "injection_limits",
    "liquid_limits",
    "production_floors",
    "watercut_limits",
)


def constraints_to_json(c: Constraints) -> dict[str, Any]:
    return {
        "injection_limits": {str(y): float(v) for y, v in sorted(c.injection_limits.items())},
        "liquid_limits": {str(y): float(v) for y, v in sorted(c.liquid_limits.items())},
        "production_floors": {str(y): float(v) for y, v in sorted(c.production_floors.items())},
        "watercut_limits": {str(y): float(v) for y, v in sorted(c.watercut_limits.items())},
        "well_outages": [
            {
                "well": o.well,
                "control_step_from": o.control_step_from,
                "control_step_to": o.control_step_to,
            }
            for o in c.well_outages
        ],
        "infrastructure": dict(c.infrastructure),
    }


def _require_mapping(document: Any, section: str) -> dict[str, Any]:
    if section not in document:
        return {}
    value = document[section]
    if not isinstance(value, dict):
        raise ValueError(f"{section}: ожидается объект год -> значение, получено {type(value).__name__}")
    return value


def _parse_year(section: str, raw: Any) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"{section}: год должен быть целым числом, получено {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        try:
            return int(text)
        except ValueError as error:
            raise ValueError(f"{section}: год должен быть целым числом, получено {raw!r}") from error
    raise ValueError(f"{section}: год должен быть целым числом, получено {raw!r}")


def _parse_amount(section: str, year: int, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{section}[{year}]: значение должно быть числом, получено {raw!r}")
    value = float(raw)
    if value != value:
        raise ValueError(f"{section}[{year}]: NaN не допускается")
    if value < 0.0:
        raise ValueError(f"{section}[{year}]: лимит не может быть отрицательным, получено {value}")
    if section == "watercut_limits" and value > 1.0:
        raise ValueError(
            f"watercut_limits[{year}]: обводнённость задаётся долей 0..1, "
            f"получено {value} — похоже на проценты"
        )
    return value


def _parse_year_map(document: dict[str, Any], section: str) -> dict[int, float]:
    result: dict[int, float] = {}
    for raw_year, raw_value in _require_mapping(document, section).items():
        year = _parse_year(section, raw_year)
        if year in result:
            raise ValueError(f"{section}: год {year} встречается дважды")
        result[year] = _parse_amount(section, year, raw_value)
    return result


def _parse_step(field: str, index: int, raw: Any, n_intervals: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"well_outages[{index}].{field}: шаг должен быть целым числом, получено {raw!r}")
    if raw < 0 or raw >= n_intervals:
        raise ValueError(
            f"well_outages[{index}].{field}: шаг {raw} вне горизонта 0..{n_intervals - 1}"
        )
    return raw


def _parse_outages(document: dict[str, Any], n_intervals: int) -> tuple[WellOutage, ...]:
    raw_outages = document.get("well_outages", [])
    if not isinstance(raw_outages, list):
        raise ValueError(f"well_outages: ожидается массив, получено {type(raw_outages).__name__}")
    outages: list[WellOutage] = []
    for index, raw in enumerate(raw_outages):
        if not isinstance(raw, dict):
            raise ValueError(f"well_outages[{index}]: ожидается объект, получено {type(raw).__name__}")
        well = raw.get("well")
        if not isinstance(well, str) or not well:
            raise ValueError(f"well_outages[{index}].well: идентификатор скважины — непустая строка")
        step_from = _parse_step("control_step_from", index, raw.get("control_step_from"), n_intervals)
        step_to = _parse_step("control_step_to", index, raw.get("control_step_to"), n_intervals)
        if step_from > step_to:
            raise ValueError(
                f"well_outages[{index}]: control_step_from={step_from} больше control_step_to={step_to}"
            )
        outages.append(
            WellOutage(well=well, control_step_from=step_from, control_step_to=step_to)
        )
    return tuple(outages)


def constraints_from_json(d: dict[str, Any], n_intervals: int = 224) -> Constraints:
    if not isinstance(d, dict):
        raise ValueError(f"документ Constraints: ожидается объект, получено {type(d).__name__}")
    if n_intervals <= 0:
        raise ValueError(f"n_intervals должно быть положительным, получено {n_intervals}")
    unknown = set(d) - set(YEAR_SECTIONS) - {"well_outages", "infrastructure"}
    if unknown:
        raise ValueError(f"неизвестные разделы документа: {', '.join(sorted(unknown))}")
    infrastructure = d.get("infrastructure", {})
    if not isinstance(infrastructure, dict):
        raise ValueError(
            f"infrastructure: ожидается объект ключ-значение, получено {type(infrastructure).__name__}"
        )
    return Constraints(
        injection_limits=_parse_year_map(d, "injection_limits"),
        liquid_limits=_parse_year_map(d, "liquid_limits"),
        production_floors=_parse_year_map(d, "production_floors"),
        watercut_limits=_parse_year_map(d, "watercut_limits"),
        well_outages=_parse_outages(d, n_intervals),
        infrastructure=dict(infrastructure),
    )


def _constraints_summary(c: Constraints) -> dict[str, Any]:
    years: set[int] = set()
    for section in YEAR_SECTIONS:
        years.update(getattr(c, section))
    return {
        "injection_limits": len(c.injection_limits),
        "liquid_limits": len(c.liquid_limits),
        "production_floors": len(c.production_floors),
        "watercut_limits": len(c.watercut_limits),
        "well_outages": len(c.well_outages),
        "infrastructure": len(c.infrastructure),
        "years": sorted(years),
        "outage_wells": sorted({o.well for o in c.well_outages}),
        "empty": not (years or c.well_outages or c.infrastructure),
    }


def build_scenario_index(artifact_paths: list[Path]) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    submitted: list[str] = []
    for path in artifact_paths:
        artifact = load_bundle(path)
        scenario_id = Path(path).stem
        is_submitted = artifact.final_npv is not None
        if is_submitted:
            submitted.append(scenario_id)
        scenarios.append(
            {
                "id": scenario_id,
                "config_hash": artifact.config_hash,
                "converged": artifact.converged,
                "self_consistent": artifact.self_consistent,
                "is_submitted": is_submitted,
                "npv_methodology": (
                    artifact.final_npv.npv_methodology if artifact.final_npv is not None else None
                ),
                "constraints": _constraints_summary(artifact.constraints),
            }
        )
    if len(submitted) > 1:
        raise ValueError(
            "final_npv заполнен более чем у одного сценария "
            f"({', '.join(sorted(submitted))}): сдан может быть ровно один"
        )
    return {"scenarios": scenarios, "submitted": submitted[0] if submitted else None}


def export_scenarios_json(artifact_paths: list[Path], out_path: str | Path) -> Path:
    index = build_scenario_index(artifact_paths)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
