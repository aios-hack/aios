from __future__ import annotations
import hashlib
import math
from typing import Any
from backend.contexts.constraints.domain.constraints import Constraints, WellOutage
from backend.contexts.schedule.domain.schedule import N_INTERVALS
from backend.shared.hashing import canonical_bytes
YEAR_SECTIONS = (
    "injection_limits",
    "liquid_limits",
    "production_floors",
    "oil_limits",
    "watercut_limits",
)

def constraints_to_json(c: Constraints) -> dict[str, Any]:
    return {
        "injection_limits": {str(y): float(v) for y, v in sorted(c.injection_limits.items())},
        "liquid_limits": {str(y): float(v) for y, v in sorted(c.liquid_limits.items())},
        "production_floors": {str(y): float(v) for y, v in sorted(c.production_floors.items())},
        "oil_limits": {str(y): float(v) for y, v in sorted(c.oil_limits.items())},
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
        raise ValueError(f"{section}: expected an object of year -> value, got {type(value).__name__}")
    return value


def _parse_year(section: str, raw: Any) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"{section}: the year must be an integer, got {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        try:
            return int(text)
        except ValueError as error:
            raise ValueError(f"{section}: the year must be an integer, got {raw!r}") from error
    raise ValueError(f"{section}: the year must be an integer, got {raw!r}")


def _parse_amount(section: str, year: int, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{section}[{year}]: the value must be a number, got {raw!r}")
    value = float(raw)
    if value != value:
        raise ValueError(f"{section}[{year}]: NaN is not allowed")
    if value < 0.0:
        raise ValueError(f"{section}[{year}]: the limit cannot be negative, got {value}")
    if section == "watercut_limits" and value > 1.0:
        raise ValueError(
            f"watercut_limits[{year}]: water cut is given as a fraction 0..1, "
            f"got {value} — this looks like percent"
        )
    return value


def _parse_year_map(document: dict[str, Any], section: str) -> dict[int, float]:
    result: dict[int, float] = {}
    for raw_year, raw_value in _require_mapping(document, section).items():
        year = _parse_year(section, raw_year)
        if year in result:
            raise ValueError(f"{section}: year {year} occurs twice")
        result[year] = _parse_amount(section, year, raw_value)
    return result


def _parse_step(field: str, index: int, raw: Any, n_intervals: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"well_outages[{index}].{field}: the step must be an integer, got {raw!r}")
    if raw < 0 or raw >= n_intervals:
        raise ValueError(
            f"well_outages[{index}].{field}: step {raw} outside the horizon 0..{n_intervals - 1}"
        )
    return raw


def _parse_outages(document: dict[str, Any], n_intervals: int) -> tuple[WellOutage, ...]:
    raw_outages = document.get("well_outages", [])
    if not isinstance(raw_outages, list):
        raise ValueError(f"well_outages: expected an array, got {type(raw_outages).__name__}")
    outages: list[WellOutage] = []
    for index, raw in enumerate(raw_outages):
        if not isinstance(raw, dict):
            raise ValueError(f"well_outages[{index}]: expected an object, got {type(raw).__name__}")
        well = raw.get("well")
        if not isinstance(well, str) or not well:
            raise ValueError(f"well_outages[{index}].well: the well identifier must be a non-empty string")
        step_from = _parse_step("control_step_from", index, raw.get("control_step_from"), n_intervals)
        step_to = _parse_step("control_step_to", index, raw.get("control_step_to"), n_intervals)
        if step_from > step_to:
            raise ValueError(
                f"well_outages[{index}]: control_step_from={step_from} exceeds control_step_to={step_to}"
            )
        outages.append(
            WellOutage(well=well, control_step_from=step_from, control_step_to=step_to)
        )
    return tuple(outages)


def constraints_from_json(d: dict[str, Any], n_intervals: int = N_INTERVALS) -> Constraints:
    if not isinstance(d, dict):
        raise ValueError(f"Constraints document: expected an object, got {type(d).__name__}")
    if n_intervals <= 0:
        raise ValueError(f"n_intervals must be positive, got {n_intervals}")
    unknown = set(d) - set(YEAR_SECTIONS) - {"well_outages", "infrastructure"}
    if unknown:
        raise ValueError(f"unknown document sections: {', '.join(sorted(unknown))}")
    infrastructure = d.get("infrastructure", {})
    if not isinstance(infrastructure, dict):
        raise ValueError(
            f"infrastructure: expected a key-value object, got {type(infrastructure).__name__}"
        )
    return Constraints(
        injection_limits=_parse_year_map(d, "injection_limits"),
        liquid_limits=_parse_year_map(d, "liquid_limits"),
        production_floors=_parse_year_map(d, "production_floors"),
        oil_limits=_parse_year_map(d, "oil_limits"),
        watercut_limits=_parse_year_map(d, "watercut_limits"),
        well_outages=_parse_outages(d, n_intervals),
        infrastructure=dict(infrastructure),
    )


def constraints_hash(constraints: Constraints) -> str:
    return hashlib.sha256(canonical_bytes(constraints_to_json(constraints))).hexdigest()
