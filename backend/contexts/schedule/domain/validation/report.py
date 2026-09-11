from __future__ import annotations

from backend.shared.errors import (
    ValidationError,
)
from collections.abc import (
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from backend.core.contracts import (
    ActiveControlMode,
    CompensationPolicy,
    Constraints,
    Role,
    compensation_policy,
)
from backend.contexts.schedule.domain.validate import (
    ConstraintCheck,
    ValidationReport,
    Violation,
    ViolationKind,
)


ACHIEVEMENT_THRESHOLD: float = 0.999


@dataclass(frozen=True, slots=True)
class FieldSeries:
    field_pressure_bar: tuple[float, ...]
    oil_produced_cum_m3: tuple[float, ...] = ()
    water_produced_cum_m3: tuple[float, ...] = ()
    water_injected_cum_m3: tuple[float, ...] = ()
    oil_in_place_m3: tuple[float, ...] = ()
    water_in_place_m3: tuple[float, ...] = ()

    @property
    def has_material_balance(self) -> bool:
        return bool(
            self.oil_produced_cum_m3
            and self.water_produced_cum_m3
            and self.water_injected_cum_m3
            and self.oil_in_place_m3
            and self.water_in_place_m3
        )


@dataclass(frozen=True, slots=True)
class RegionSeries:
    region_pressure_bar: Mapping[int, tuple[float, ...]]

    @property
    def regions(self) -> tuple[int, ...]:
        return tuple(sorted(self.region_pressure_bar))

    @property
    def has_regions(self) -> bool:
        return bool(self.region_pressure_bar)


BLOCKING_DYNAMIC_VIOLATION_KINDS: frozenset[ViolationKind] = frozenset(
    {
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
        ViolationKind.ROLE_FACT_MISMATCH,
        ViolationKind.SHUT_WITH_FLOW,
        ViolationKind.RESPONSE_AXIS_INCOMPLETE,
        ViolationKind.LIQUID_LIMIT_EXCEEDED,
        ViolationKind.INJECTION_LIMIT_EXCEEDED,
        ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED,
        ViolationKind.PRODUCTION_FLOOR_MISSED,
        ViolationKind.OIL_LIMIT_EXCEEDED,
        ViolationKind.WATERCUT_LIMIT_EXCEEDED,
        ViolationKind.OUTAGE_WELL_PRODUCED,
        ViolationKind.FIELD_PRESSURE_BELOW_FLOOR,
        ViolationKind.FIELD_PRESSURE_ABOVE_CEILING,
        ViolationKind.REGION_PRESSURE_BELOW_FLOOR,
        ViolationKind.REGION_PRESSURE_ABOVE_CEILING,
    }
)


def blocking_dynamic_violation_kinds(
    constraints: Constraints | None = None,
) -> frozenset[ViolationKind]:
    if constraints is None:
        return BLOCKING_DYNAMIC_VIOLATION_KINDS
    policy = compensation_policy(constraints)
    return blocking_kinds_for_compensation(policy)


def blocking_kinds_for_compensation(
    policy: CompensationPolicy,
) -> frozenset[ViolationKind]:
    if not (policy.enabled and policy.hard):
        return BLOCKING_DYNAMIC_VIOLATION_KINDS
    return BLOCKING_DYNAMIC_VIOLATION_KINDS | {
        ViolationKind.COMPENSATION_OUT_OF_CORRIDOR,
        ViolationKind.COMPENSATION_UNDEFINED,
    }


def ordered_violation_kinds(
    kinds: frozenset[ViolationKind] | Iterable[ViolationKind],
) -> tuple[ViolationKind, ...]:
    return tuple(sorted(kinds, key=lambda kind: kind.value))


@dataclass(frozen=True, slots=True)
class TargetRatio:
    control_step: int
    well: str
    role: Role
    target: float
    actual: float
    mode: ActiveControlMode

    @property
    def ratio(self) -> float:
        return self.actual / self.target

    @property
    def achieved(self) -> bool:
        return self.ratio >= ACHIEVEMENT_THRESHOLD


@dataclass(frozen=True, slots=True)
class DynamicReport:
    report: ValidationReport
    ratios: tuple[TargetRatio, ...]
    n_states: int
    n_intervals_seen: int
    n_wells: int
    blocking_kinds: tuple[ViolationKind, ...] = ordered_violation_kinds(
        BLOCKING_DYNAMIC_VIOLATION_KINDS
    )
    constraint_checks: tuple[ConstraintCheck, ...] = ()

    @property
    def ok(self) -> bool:
        return self.report.ok

    @property
    def blocking_violations(self) -> tuple[Violation, ...]:
        return tuple(
            item
            for item in self.report.violations
            if item.kind in self.blocking_kinds
        )

    @property
    def blocking_ok(self) -> bool:
        return not self.blocking_violations

    @property
    def violations(self) -> tuple[Violation, ...]:
        return self.report.violations

    def counts(self) -> dict[ViolationKind, int]:
        return self.report.counts()

    def by_kind(self) -> dict[ViolationKind, tuple[Violation, ...]]:
        return self.report.by_kind()

    def format(self, limit: int = 50) -> str:
        return self.report.format(limit)

    def undershooting(self) -> tuple[TargetRatio, ...]:
        return tuple(item for item in self.ratios if not item.achieved)

    def modes(self) -> dict[ActiveControlMode, int]:
        counts: dict[ActiveControlMode, int] = {}
        for item in self.ratios:
            counts[item.mode] = counts.get(item.mode, 0) + 1
        return counts

    def raise_if_violated(self) -> None:
        if not self.ok:
            raise DynamicValidationError(self.format(), self)


class DynamicValidationError(ValidationError):
    default_code = "schedule.dynamic"

    def __init__(self, message: str, report: DynamicReport) -> None:
        super().__init__(message)
        self.report = report


__all__ = [
    "ACHIEVEMENT_THRESHOLD",
    "BLOCKING_DYNAMIC_VIOLATION_KINDS",
    "DynamicReport",
    "DynamicValidationError",
    "FieldSeries",
    "RegionSeries",
    "TargetRatio",
    "blocking_dynamic_violation_kinds",
    "blocking_kinds_for_compensation",
    "ordered_violation_kinds",
]
