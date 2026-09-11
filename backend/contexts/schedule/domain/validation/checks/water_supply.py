from __future__ import annotations

from backend.contexts.schedule.domain.validation.coverage import (
    constraint_kinds,
)
from backend.contexts.schedule.domain.validation.outcomes import (
    _checked,
    _not_set,
)
from backend.contexts.schedule.domain.validation.report import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
)
from calendar import monthrange
from collections.abc import (
    Sequence,
)
from backend.core.contracts import (
    Constraints,
    IntervalResponse,
    Schedule,
    water_supply_policy,
)
from backend.contexts.constraints.domain.constraints import (
    EXTERNAL_WATER_M3_PER_DAY,
    WATER_REINJECTION_FRACTION,
    WATER_REINJECTION_LAG_STEPS,
    WATER_SUPPLY_UNLIMITED,
    limit_origin,
)
from backend.contexts.schedule.domain.validate import (
    STATUS_WAIVED,
    CONSTRAINT_WATER_SUPPLY,
    ConstraintCheck,
    Violation,
    ViolationKind,
)


def _days_in_step(schedule: Schedule, control_step: int) -> int:
    month_index = schedule.meta.t0.month - 1 + control_step
    year = schedule.meta.t0.year + month_index // 12
    month = month_index % 12 + 1
    return monthrange(year, month)[1]


def _check_water_supply(
    schedule: Schedule,
    interval_responses: Sequence[IntervalResponse],
    constraints: Constraints,
    oil_density_t_per_m3: float | None,
) -> tuple[tuple[Violation, ...], tuple[ConstraintCheck, ...]]:
    policy = water_supply_policy(constraints)
    if policy.unlimited:
        return (), (
            ConstraintCheck(
                constraint=CONSTRAINT_WATER_SUPPLY,
                status=STATUS_WAIVED,
                kinds=constraint_kinds(CONSTRAINT_WATER_SUPPLY),
                n_violations=None,
                blocking=False,
                enforcement=None,
                detail=(
                    f"infrastructure.{WATER_SUPPLY_UNLIMITED} = true: кейс "
                    "объявил источник воды неограниченным, материальный баланс "
                    "воды снят явно, а не пропущен"
                ),
            ),
        )
    if not policy.enabled:
        return (), (
            _not_set(
                CONSTRAINT_WATER_SUPPLY,
                (
                    f"ни {WATER_REINJECTION_FRACTION}, ни "
                    f"{WATER_REINJECTION_LAG_STEPS}, ни "
                    f"{EXTERNAL_WATER_M3_PER_DAY} в infrastructure не заданы: "
                    "материальный баланс воды не проверялся"
                ),
            ),
        )
    if oil_density_t_per_m3 is None or oil_density_t_per_m3 <= 0.0:
        raise ValueError(
            "water_reinjection_fraction задан, но положительная плотность "
            "нефти не передана: объём добытой воды не определён"
        )

    totals: dict[int, tuple[float, float, float]] = {}
    for item in interval_responses:
        oil, liquid, injection = totals.get(item.control_step, (0.0, 0.0, 0.0))
        totals[item.control_step] = (
            oil + max(0.0, item.oil_mass_delta),
            liquid + max(0.0, item.liquid_volume_delta),
            injection + max(0.0, item.injection_volume_delta),
        )
    produced_water = {
        step: max(0.0, liquid - oil / oil_density_t_per_m3)
        for step, (oil, liquid, _) in totals.items()
    }
    origin = limit_origin(constraints, WATER_REINJECTION_FRACTION)
    found: list[Violation] = []
    for control_step in range(schedule.meta.n_intervals):
        injection = totals.get(control_step, (0.0, 0.0, 0.0))[2]
        source_step = control_step - policy.lag_steps
        source_water = produced_water.get(source_step, 0.0)
        available = (
            policy.external_water_m3_per_day
            * _days_in_step(schedule, control_step)
            + float(policy.reinjection_fraction or 0.0) * source_water
        )
        if injection <= available + 1.0e-6:
            continue
        found.append(
            Violation(
                kind=ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED,
                control_step=control_step,
                well=None,
                value=injection,
                detail=(
                    f"закачано {injection:.3f} м³ при доступном материальном "
                    f"балансе воды {available:.3f} м³; источник: "
                    f"{policy.reinjection_fraction} × добытая вода шага "
                    f"{source_step} + {policy.external_water_m3_per_day} м³/сут; "
                    f"предел infrastructure.{WATER_REINJECTION_FRACTION}, "
                    f"{origin}"
                ),
            )
        )
    return tuple(found), (
        _checked(
            CONSTRAINT_WATER_SUPPLY,
            found,
            (
                f"доля возврата {policy.reinjection_fraction}, лаг "
                f"{policy.lag_steps} шагов, внешний приток "
                f"{policy.external_water_m3_per_day} м³/сут: закачка сверена "
                f"с балансом воды на {schedule.meta.n_intervals} шагах"
            ),
            blocking_kinds=BLOCKING_DYNAMIC_VIOLATION_KINDS,
        ),
    )
