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
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.schedule.domain.schedule import Schedule
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
            f"floor infrastructure.{PRESSURE_FLOOR_BAR} = "
            f"{limits.floor_bar} bar, "
            f"{limit_origin(constraints, PRESSURE_FLOOR_BAR)}"
        )
    if limits.ceiling_bar is not None:
        parts.append(
            f"ceiling infrastructure.{PRESSURE_CEILING_BAR} = "
            f"{limits.ceiling_bar} bar, "
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
                    f"neither infrastructure.{PRESSURE_FLOOR_BAR} nor "
                    f"infrastructure.{PRESSURE_CEILING_BAR} is set in the "
                    "case: reservoir pressure was not checked, and a limit "
                    "must not be assigned on behalf of the organizers"
                ),
            ),
        )
    if field_series is None:
        raise ValueError(
            f"infrastructure.{PRESSURE_FLOOR_BAR}/{PRESSURE_CEILING_BAR} "
            "are set, but the reservoir pressure series was not supplied: "
            "the pressure policy is enabled and there is nothing to check. "
            "Pressure is known only after an OPM run, so the validator must "
            "either receive FPR or raise an error, and must not declare the "
            "schedule admissible"
        )
    pressures = field_series.field_pressure_bar
    if not pressures:
        raise ValueError(
            f"infrastructure.{PRESSURE_FLOOR_BAR}/{PRESSURE_CEILING_BAR} "
            "are set, but the FPR series is empty: there is nothing to "
            "compare against the limit"
        )
    n_intervals = schedule.meta.n_intervals
    required = level_deck_date_index(n_intervals - 1) + 1
    if len(pressures) < required:
        raise ValueError(
            f"the FPR series is shorter than the horizon: {len(pressures)} "
            f"values against the required {required} = "
            f"{FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + {n_intervals}; the "
            f"pressure level of control step {n_intervals - 1} is read at "
            f"deck date index {level_deck_date_index(n_intervals - 1)}"
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
                        f"average reservoir pressure {value:.3f} bar is "
                        f"below the floor {limits.floor_bar} bar; {source}"
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
                        f"average reservoir pressure {value:.3f} bar is "
                        f"above the ceiling {limits.ceiling_bar} bar; "
                        f"{source}"
                    ),
                )
            )
    return tuple(found), (
        _checked(
            CONSTRAINT_FIELD_PRESSURE,
            found,
            (
                f"reservoir pressure checked over {n_intervals} control "
                f"steps against FPR, the level of step k is read at deck "
                f"date index {FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + k; "
                f"{source}"
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
            f"floor infrastructure.{REGION_PRESSURE_FLOOR_BAR} = "
            f"{limits.floor_bar} bar, "
            f"{limit_origin(constraints, REGION_PRESSURE_FLOOR_BAR)}"
        )
    if limits.ceiling_bar is not None:
        parts.append(
            f"ceiling infrastructure.{REGION_PRESSURE_CEILING_BAR} = "
            f"{limits.ceiling_bar} bar, "
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
                    f"neither infrastructure.{REGION_PRESSURE_FLOOR_BAR} "
                    f"nor infrastructure.{REGION_PRESSURE_CEILING_BAR} is "
                    "set in the case: regional reservoir pressure was not "
                    "checked, and a limit must not be assigned on behalf of "
                    "the organizers"
                ),
            ),
        )
    if region_series is None:
        raise ValueError(
            f"infrastructure.{REGION_PRESSURE_FLOOR_BAR}/"
            f"{REGION_PRESSURE_CEILING_BAR} are set, but the regional "
            "pressure series were not supplied: the policy is enabled and "
            "there is nothing to check. Per-region RPR appears only in a run "
            "of the diagnostic deck with FIPNUM, so the validator must "
            "either receive the series or raise an error, and must not "
            "declare the schedule admissible"
        )
    if not region_series.has_regions:
        raise ValueError(
            f"infrastructure.{REGION_PRESSURE_FLOOR_BAR}/"
            f"{REGION_PRESSURE_CEILING_BAR} are set, but the RPR series are "
            "empty: there is nothing to compare against the limit"
        )
    n_intervals = schedule.meta.n_intervals
    required = level_deck_date_index(n_intervals - 1) + 1
    for region in region_series.regions:
        pressures = region_series.region_pressure_bar[region]
        if len(pressures) < required:
            raise ValueError(
                f"the RPR series of region {region} is shorter than the "
                f"horizon: {len(pressures)} values against the required "
                f"{required} = {FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + "
                f"{n_intervals}; the pressure level of control step "
                f"{n_intervals - 1} is read at deck date index "
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
                            f"reservoir pressure of region {region} "
                            f"{value:.3f} bar is below the floor "
                            f"{limits.floor_bar} bar; {source}"
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
                            f"reservoir pressure of region {region} "
                            f"{value:.3f} bar is above the ceiling "
                            f"{limits.ceiling_bar} bar; {source}"
                        ),
                        region=region,
                    )
                )
    return tuple(found), (
        _checked(
            CONSTRAINT_REGION_PRESSURE,
            found,
            (
                f"regional reservoir pressure checked over {n_intervals} "
                f"control steps against RPR of regions "
                f"{', '.join(str(item) for item in region_series.regions)}, "
                f"the level of step k is read at deck date index "
                f"{FIRST_CONTROL_LEVEL_DECK_DATE_INDEX} + k; {source}"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


__all__ = [
    "check_field_pressure",
    "check_region_pressure",
]
