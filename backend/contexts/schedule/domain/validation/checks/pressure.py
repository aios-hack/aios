from __future__ import annotations

from backend.contexts.schedule.domain.validation.constants import (
    FIRST_CONTROL_LEVEL_DECK_DATE_INDEX,
)

from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
    _not_set,
)
from backend.contexts.schedule.domain.validation.interpreter import (
    level_deck_date_index,
)
from backend.contexts.schedule.domain.validation.report import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    FieldSeries,
    RegionSeries,
)
from backend.core.contracts import (
    Constraints,
    Schedule,
)
from backend.contexts.constraints.domain.constraints import (
    PRESSURE_CEILING_BAR,
    PRESSURE_FLOOR_BAR,
    REGION_PRESSURE_CEILING_BAR,
    REGION_PRESSURE_FLOOR_BAR,
    FieldPressureLimits,
    RegionPressureLimits,
    field_pressure_limits,
    limit_origin,
    region_pressure_limits,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_FIELD_PRESSURE,
    CONSTRAINT_REGION_PRESSURE,
    ConstraintCheck,
    Violation,
    ViolationKind,
)


def _pressure_source(constraints: Constraints, limits: FieldPressureLimits) -> str:
    parts: list[str] = []
    if limits.floor_bar is not None:
        parts.append(
            f"пол infrastructure.{PRESSURE_FLOOR_BAR} = {limits.floor_bar} бар, "
            f"{limit_origin(constraints, PRESSURE_FLOOR_BAR)}"
        )
    if limits.ceiling_bar is not None:
        parts.append(
            f"потолок infrastructure.{PRESSURE_CEILING_BAR} = "
            f"{limits.ceiling_bar} бар, "
            f"{limit_origin(constraints, PRESSURE_CEILING_BAR)}"
        )
    return "; ".join(parts)


def check_field_pressure(
    schedule: Schedule,
    constraints: Constraints,
    field_series: FieldSeries | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    limits = field_pressure_limits(constraints)
    if not limits.enabled:
        return (), (
            _not_set(
                CONSTRAINT_FIELD_PRESSURE,
                (
                    f"ни infrastructure.{PRESSURE_FLOOR_BAR}, ни "
                    f"infrastructure.{PRESSURE_CEILING_BAR} в кейсе не заданы: "
                    "пластовое давление не проверялось, предел назначать "
                    "за организаторов нельзя"
                ),
            ),
        )
    if field_series is None:
        raise ValueError(
            f"infrastructure.{PRESSURE_FLOOR_BAR}/{PRESSURE_CEILING_BAR} "
            "заданы, но серия пластового давления не передана: политика "
            "давления включена, а проверять нечего. Давление известно только "
            "после прогона OPM, поэтому валидатор обязан получить FPR "
            "или сообщить об ошибке, а не признать расписание допустимым"
        )
    pressures = field_series.field_pressure_bar
    if not pressures:
        raise ValueError(
            f"infrastructure.{PRESSURE_FLOOR_BAR}/{PRESSURE_CEILING_BAR} "
            "заданы, но серия FPR пуста: сравнивать с пределом нечего"
        )
    n_intervals = schedule.meta.n_intervals
    required = level_deck_date_index(n_intervals - 1) + 1
    if len(pressures) < required:
        raise ValueError(
            f"серия FPR короче горизонта: {len(pressures)} значений при "
            f"необходимых {required} = {FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + "
            f"{n_intervals}; уровень давления шага управления "
            f"{n_intervals - 1} читается по индексу дека "
            f"{level_deck_date_index(n_intervals - 1)}"
        )
    source = _pressure_source(constraints, limits)
    found: list[Violation] = []
    for control_step in range(n_intervals):
        value = pressures[level_deck_date_index(control_step)]
        if limits.floor_bar is not None and value < limits.floor_bar:
            found.append(
                Violation(
                    kind=ViolationKind.FIELD_PRESSURE_BELOW_FLOOR,
                    control_step=control_step,
                    well=None,
                    value=value,
                    detail=(
                        f"среднее пластовое давление {value:.3f} бар ниже пола "
                        f"{limits.floor_bar} бар; {source}"
                    ),
                )
            )
        if limits.ceiling_bar is not None and value > limits.ceiling_bar:
            found.append(
                Violation(
                    kind=ViolationKind.FIELD_PRESSURE_ABOVE_CEILING,
                    control_step=control_step,
                    well=None,
                    value=value,
                    detail=(
                        f"среднее пластовое давление {value:.3f} бар выше "
                        f"потолка {limits.ceiling_bar} бар; {source}"
                    ),
                )
            )
    return tuple(found), (
        _checked(
            CONSTRAINT_FIELD_PRESSURE,
            found,
            (
                f"пластовое давление сверено на {n_intervals} шагах управления "
                f"по FPR, уровень шага k читается по индексу дека "
                f"{FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + k; {source}"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


def _region_pressure_source(
    constraints: Constraints, limits: RegionPressureLimits
) -> str:
    parts: list[str] = []
    if limits.floor_bar is not None:
        parts.append(
            f"пол infrastructure.{REGION_PRESSURE_FLOOR_BAR} = "
            f"{limits.floor_bar} бар, "
            f"{limit_origin(constraints, REGION_PRESSURE_FLOOR_BAR)}"
        )
    if limits.ceiling_bar is not None:
        parts.append(
            f"потолок infrastructure.{REGION_PRESSURE_CEILING_BAR} = "
            f"{limits.ceiling_bar} бар, "
            f"{limit_origin(constraints, REGION_PRESSURE_CEILING_BAR)}"
        )
    return "; ".join(parts)


def check_region_pressure(
    schedule: Schedule,
    constraints: Constraints,
    region_series: RegionSeries | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    limits = region_pressure_limits(constraints)
    if not limits.enabled:
        return (), (
            _not_set(
                CONSTRAINT_REGION_PRESSURE,
                (
                    f"ни infrastructure.{REGION_PRESSURE_FLOOR_BAR}, ни "
                    f"infrastructure.{REGION_PRESSURE_CEILING_BAR} в кейсе "
                    "не заданы: региональное пластовое давление не "
                    "проверялось, предел назначать за организаторов нельзя"
                ),
            ),
        )
    if region_series is None:
        raise ValueError(
            f"infrastructure.{REGION_PRESSURE_FLOOR_BAR}/"
            f"{REGION_PRESSURE_CEILING_BAR} заданы, но серии регионального "
            "давления не переданы: политика включена, а проверять нечего. "
            "RPR по регионам появляется только в прогоне диагностического "
            "дека с FIPNUM, поэтому валидатор обязан получить серии или "
            "сообщить об ошибке, а не признать расписание допустимым"
        )
    if not region_series.has_regions:
        raise ValueError(
            f"infrastructure.{REGION_PRESSURE_FLOOR_BAR}/"
            f"{REGION_PRESSURE_CEILING_BAR} заданы, но серии RPR пусты: "
            "сравнивать с пределом нечего"
        )
    n_intervals = schedule.meta.n_intervals
    required = level_deck_date_index(n_intervals - 1) + 1
    for region in region_series.regions:
        pressures = region_series.region_pressure_bar[region]
        if len(pressures) < required:
            raise ValueError(
                f"серия RPR региона {region} короче горизонта: "
                f"{len(pressures)} значений при необходимых {required} = "
                f"{FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + {n_intervals}; "
                f"уровень давления шага управления {n_intervals - 1} "
                f"читается по индексу дека "
                f"{level_deck_date_index(n_intervals - 1)}"
            )
    source = _region_pressure_source(constraints, limits)
    found: list[Violation] = []
    for region in region_series.regions:
        pressures = region_series.region_pressure_bar[region]
        for control_step in range(n_intervals):
            value = pressures[level_deck_date_index(control_step)]
            if limits.floor_bar is not None and value < limits.floor_bar:
                found.append(
                    Violation(
                        kind=ViolationKind.REGION_PRESSURE_BELOW_FLOOR,
                        control_step=control_step,
                        well=None,
                        value=value,
                        detail=(
                            f"пластовое давление региона {region} "
                            f"{value:.3f} бар ниже пола {limits.floor_bar} "
                            f"бар; {source}"
                        ),
                        region=region,
                    )
                )
            if limits.ceiling_bar is not None and value > limits.ceiling_bar:
                found.append(
                    Violation(
                        kind=ViolationKind.REGION_PRESSURE_ABOVE_CEILING,
                        control_step=control_step,
                        well=None,
                        value=value,
                        detail=(
                            f"пластовое давление региона {region} "
                            f"{value:.3f} бар выше потолка "
                            f"{limits.ceiling_bar} бар; {source}"
                        ),
                        region=region,
                    )
                )
    return tuple(found), (
        _checked(
            CONSTRAINT_REGION_PRESSURE,
            found,
            (
                f"региональное пластовое давление сверено на {n_intervals} "
                f"шагах управления по RPR регионов "
                f"{', '.join(str(item) for item in region_series.regions)}, "
                f"уровень шага k читается по индексу дека "
                f"{FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + k; {source}"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


__all__ = [
    "check_field_pressure",
    "check_region_pressure",
]
