from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from backend.core.contracts import (
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    N_INTERVALS,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellOutage,
    WellState,
    compensation_policy,
    water_supply_policy,
)
from backend.contexts.constraints.domain.constraints import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
    BLOCKING_INFRASTRUCTURE_KEYS,
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_MAX,
    COMPENSATION_MIN,
    COMPENSATION_SCOPE,
    CONSTRAINT_SOURCES,
    EXTERNAL_WATER_M3_PER_DAY,
    PRESSURE_CEILING_BAR,
    PRESSURE_FLOOR_BAR,
    REGION_PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    SOURCED_INFRASTRUCTURE_KEYS,
    SOURCE_SUFFIX,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    WATER_SAFETY_FACTOR,
    WATER_SUPPLY_UNLIMITED,
    bhp_limits,
    region_pressure_limits,
    source_key,
)
from backend.contexts.schedule.infrastructure.json_io import load_schedule_json

YEAR_SECTIONS: tuple[str, ...] = (
    "injection_limits",
    "liquid_limits",
    "production_floors",
    "oil_limits",
    "watercut_limits",
)

TOP_LEVEL_SECTIONS: tuple[str, ...] = YEAR_SECTIONS + ("well_outages", "infrastructure")

INFRASTRUCTURE_VALUE_KEYS: tuple[str, ...] = (
    WATER_SUPPLY_UNLIMITED,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    EXTERNAL_WATER_M3_PER_DAY,
    WATER_SAFETY_FACTOR,
    COMPENSATION_MIN,
    COMPENSATION_MAX,
    COMPENSATION_ENFORCEMENT,
    COMPENSATION_SCOPE,
    BHP_PRODUCER_MIN_BAR,
    BHP_INJECTOR_MAX_BAR,
    PRESSURE_FLOOR_BAR,
    PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    REGION_PRESSURE_CEILING_BAR,
)

INFRASTRUCTURE_SOURCE_KEYS: tuple[str, ...] = tuple(
    source_key(key) for key in SOURCED_INFRASTRUCTURE_KEYS
)

INFRASTRUCTURE_KEYS: tuple[str, ...] = (
    INFRASTRUCTURE_VALUE_KEYS + INFRASTRUCTURE_SOURCE_KEYS
)

REFUSED_SECTIONS: dict[str, str] = {
    "new_wells": (
        "бурение новых скважин, которых нет в деке, не поддерживается: "
        "фонд Model_Z фиксирован, и оптимизатор управляет только режимами "
        "существующих скважин. Остановку скважины задавайте через well_outages"
    ),
    "commissioning_shifts": (
        "перенос плановых сроков ввода скважин пока не реализован: "
        "валидатор трактует такой сдвиг как изменение зафиксированной истории"
    ),
}


class CaseError(ValueError):
    pass


def _require_mapping(document: Any, section: str) -> dict[str, Any]:
    if section not in document:
        return {}
    value = document[section]
    if not isinstance(value, dict):
        raise CaseError(f"{section}: ожидается объект год -> значение, получено {type(value).__name__}")
    return value


def _parse_year(section: str, raw: Any) -> int:
    if isinstance(raw, bool):
        raise CaseError(f"{section}: год должен быть целым числом, получено {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        try:
            return int(text)
        except ValueError as error:
            raise CaseError(f"{section}: год должен быть целым числом, получено {raw!r}") from error
    raise CaseError(f"{section}: год должен быть целым числом, получено {raw!r}")


def _parse_amount(section: str, year: int, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise CaseError(f"{section}[{year}]: значение должно быть числом, получено {raw!r}")
    value = float(raw)
    if value != value:
        raise CaseError(f"{section}[{year}]: NaN не допускается")
    if value < 0.0:
        raise CaseError(f"{section}[{year}]: лимит не может быть отрицательным, получено {value}")
    if section == "watercut_limits" and value > 1.0:
        raise CaseError(
            f"watercut_limits[{year}]: обводнённость задаётся долей 0..1, "
            f"получено {value} — похоже на проценты"
        )
    return value


def _parse_year_map(document: dict[str, Any], section: str) -> dict[int, float]:
    result: dict[int, float] = {}
    for raw_year, raw_value in _require_mapping(document, section).items():
        year = _parse_year(section, raw_year)
        if year in result:
            raise CaseError(f"{section}: год {year} встречается дважды")
        result[year] = _parse_amount(section, year, raw_value)
    return result


def _parse_step(field: str, index: int, raw: Any, n_intervals: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise CaseError(f"well_outages[{index}].{field}: шаг должен быть целым числом, получено {raw!r}")
    if raw < 0 or raw >= n_intervals:
        raise CaseError(
            f"well_outages[{index}].{field}: шаг {raw} вне горизонта 0..{n_intervals - 1}"
        )
    return raw


def _parse_outages(document: dict[str, Any], n_intervals: int) -> tuple[WellOutage, ...]:
    raw_outages = document.get("well_outages", [])
    if not isinstance(raw_outages, list):
        raise CaseError(f"well_outages: ожидается массив, получено {type(raw_outages).__name__}")
    outages: list[WellOutage] = []
    for index, raw in enumerate(raw_outages):
        if not isinstance(raw, dict):
            raise CaseError(f"well_outages[{index}]: ожидается объект, получено {type(raw).__name__}")
        well = raw.get("well")
        if not isinstance(well, str) or not well:
            raise CaseError(f"well_outages[{index}].well: идентификатор скважины — непустая строка")
        step_from = _parse_step("control_step_from", index, raw.get("control_step_from"), n_intervals)
        step_to = _parse_step("control_step_to", index, raw.get("control_step_to"), n_intervals)
        if step_from > step_to:
            raise CaseError(
                f"well_outages[{index}]: control_step_from={step_from} больше control_step_to={step_to}"
            )
        outages.append(
            WellOutage(well=well, control_step_from=step_from, control_step_to=step_to)
        )
    return tuple(outages)


def _check_infrastructure(infrastructure: dict[str, Any]) -> None:
    if not isinstance(infrastructure, dict):
        raise CaseError(
            f"infrastructure: ожидается объект ключ-значение, получено {type(infrastructure).__name__}"
        )
    for key in infrastructure:
        if not isinstance(key, str):
            raise CaseError(f"infrastructure: имя параметра — строка, получено {key!r}")
        if key not in INFRASTRUCTURE_KEYS:
            raise CaseError(
                f"infrastructure.{key}: неизвестный параметр; допустимы "
                f"{', '.join(INFRASTRUCTURE_KEYS)}"
            )
    for key in INFRASTRUCTURE_SOURCE_KEYS:
        if key not in infrastructure:
            continue
        value = infrastructure[key]
        if not isinstance(value, str) or value not in CONSTRAINT_SOURCES:
            raise CaseError(
                f"infrastructure.{key}: источник ограничения — одно из "
                f"{', '.join(sorted(CONSTRAINT_SOURCES))}, получено {value!r}"
            )
    for key in BLOCKING_INFRASTRUCTURE_KEYS:
        if key not in infrastructure:
            continue
        if source_key(key) in infrastructure:
            continue
        raise CaseError(
            f"infrastructure.{source_key(key)}: ограничение "
            f"infrastructure.{key} блокирует расписание, поэтому его источник "
            f"обязателен; укажите одно из "
            f"{', '.join(sorted(CONSTRAINT_SOURCES))}"
        )
    for key in INFRASTRUCTURE_SOURCE_KEYS:
        if key in infrastructure and key[: -len(SOURCE_SUFFIX)] not in infrastructure:
            raise CaseError(
                f"infrastructure.{key}: источник объявлен без самого "
                f"ограничения infrastructure.{key[: -len(SOURCE_SUFFIX)]}"
            )


def constraints_from_json(d: dict[str, Any], n_intervals: int = N_INTERVALS) -> Constraints:
    if not isinstance(d, dict):
        raise CaseError(f"документ Constraints: ожидается объект, получено {type(d).__name__}")
    if n_intervals <= 0:
        raise CaseError(f"n_intervals должно быть положительным, получено {n_intervals}")
    for section, reason in REFUSED_SECTIONS.items():
        if section in d:
            raise CaseError(f"{section}: {reason}")
    unknown = set(d) - set(TOP_LEVEL_SECTIONS)
    if unknown:
        raise CaseError(
            f"неизвестные разделы документа: {', '.join(sorted(unknown))}; "
            f"допустимы {', '.join(TOP_LEVEL_SECTIONS)}"
        )
    infrastructure = d.get("infrastructure", {})
    _check_infrastructure(infrastructure)
    return Constraints(
        injection_limits=_parse_year_map(d, "injection_limits"),
        liquid_limits=_parse_year_map(d, "liquid_limits"),
        production_floors=_parse_year_map(d, "production_floors"),
        oil_limits=_parse_year_map(d, "oil_limits"),
        watercut_limits=_parse_year_map(d, "watercut_limits"),
        well_outages=_parse_outages(d, n_intervals),
        infrastructure=dict(infrastructure),
    )


def _load_meta(data: dict[str, Any]) -> ScheduleMeta:
    return ScheduleMeta(
        model=data["model"],
        t0=date.fromisoformat(data["t0"]),
        n_control_dates=data["n_control_dates"],
        n_intervals=data["n_intervals"],
        wells=tuple(data["wells"]),
        history_prefix_hash=data["history_prefix_hash"],
        fixed_events_hash=data["fixed_events_hash"],
        control_events_hash=data["control_events_hash"],
        provenance=data["provenance"],
    )


def _load_well_state(data: dict[str, Any]) -> WellState:
    return WellState(
        availability=Availability[data["availability"]],
        role=Role[data["role"]],
        operating_status=OperatingStatus[data["operating_status"]],
        setpoint=data["setpoint"],
    )










def load_case(path: str | Path, n_intervals: int = N_INTERVALS) -> Constraints:
    case_path = Path(path)
    if not case_path.is_file():
        raise CaseError(f"файл кейса не найден: {case_path}")
    try:
        text = case_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CaseError(f"файл кейса {case_path} не читается: {error}") from error
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise CaseError(
            f"{case_path}: не разбирается как JSON — {error.msg} "
            f"(строка {error.lineno}, столбец {error.colno})"
        ) from error
    try:
        constraints = constraints_from_json(document, n_intervals=n_intervals)
        water_supply_policy(constraints)
        compensation_policy(constraints)
        bhp_limits(constraints)
        region_pressure_limits(constraints)
    except ValueError as error:
        raise CaseError(f"{case_path}: {error}") from error
    return replace(constraints, case_path=str(case_path))
