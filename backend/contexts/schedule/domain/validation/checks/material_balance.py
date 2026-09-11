from __future__ import annotations

from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
    _not_set,
)

from backend.contexts.schedule.domain.validation.report import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    FieldSeries,
)
from backend.core.contracts import (
    MATERIAL_BALANCE_RELATIVE_TOLERANCE,
)
from backend.contexts.schedule.domain.validate import (
    CONSTRAINT_MATERIAL_BALANCE,
    ConstraintCheck,
    Violation,
    ViolationKind,
)
from backend.shared.numeric import relative_error


def _relative_error(delta_stock: float, delta_flow: float) -> float:
    return relative_error(delta_stock, delta_flow)


def check_material_balance(
    field_series: FieldSeries | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    if field_series is None or not field_series.has_material_balance:
        return (), (
            _not_set(
                CONSTRAINT_MATERIAL_BALANCE,
                (
                    "полевые серии FOIP/FWIP/FOPT/FWPT/FWIT не переданы: "
                    "материальный баланс пласта не проверялся"
                ),
            ),
        )
    oil_stock = (
        field_series.oil_in_place_m3[-1] - field_series.oil_in_place_m3[0]
    )
    oil_flow = (
        field_series.oil_produced_cum_m3[-1]
        - field_series.oil_produced_cum_m3[0]
    )
    water_stock = (
        field_series.water_in_place_m3[-1] - field_series.water_in_place_m3[0]
    )
    water_injected = (
        field_series.water_injected_cum_m3[-1]
        - field_series.water_injected_cum_m3[0]
    )
    water_produced = (
        field_series.water_produced_cum_m3[-1]
        - field_series.water_produced_cum_m3[0]
    )
    oil_error = _relative_error(oil_stock, -oil_flow)
    water_error = _relative_error(water_stock, water_injected - water_produced)
    found: list[Violation] = []
    if oil_error > MATERIAL_BALANCE_RELATIVE_TOLERANCE:
        found.append(
            Violation(
                kind=ViolationKind.MATERIAL_BALANCE_BROKEN,
                control_step=None,
                well=None,
                value=oil_error,
                detail=(
                    f"баланс нефти по горизонту не сходится: относительная "
                    f"невязка {oil_error:.6f} выше допуска "
                    f"{MATERIAL_BALANCE_RELATIVE_TOLERANCE}; изменение запаса "
                    f"{oil_stock:.3f} м³ против добытого {oil_flow:.3f} м³"
                ),
            )
        )
    if water_error > MATERIAL_BALANCE_RELATIVE_TOLERANCE:
        found.append(
            Violation(
                kind=ViolationKind.MATERIAL_BALANCE_BROKEN,
                control_step=None,
                well=None,
                value=water_error,
                detail=(
                    f"баланс воды по горизонту не сходится: относительная "
                    f"невязка {water_error:.6f} выше допуска "
                    f"{MATERIAL_BALANCE_RELATIVE_TOLERANCE}; изменение запаса "
                    f"{water_stock:.3f} м³ против закачанного минус добытого "
                    f"{water_injected - water_produced:.3f} м³"
                ),
            )
        )
    return tuple(found), (
        _checked(
            CONSTRAINT_MATERIAL_BALANCE,
            found,
            (
                f"материальный баланс сверен по горизонту при допуске "
                f"{MATERIAL_BALANCE_RELATIVE_TOLERANCE}: невязка по нефти "
                f"{oil_error:.6f}, по воде {water_error:.6f}"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )


__all__ = [
    "check_material_balance",
]
