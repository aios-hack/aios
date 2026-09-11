from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.shared.errors import ValidationError

MIN_SETPOINT_M3_PER_DAY: float = 0.0


class ViolationKind(Enum):
    LRAT_ABOVE_CEILING = "LRAT_ABOVE_CEILING"
    NEGATIVE_SETPOINT = "NEGATIVE_SETPOINT"
    MISSING_VALUE = "MISSING_VALUE"
    UNEXPECTED_VALUE = "UNEXPECTED_VALUE"
    STEP_OUT_OF_RANGE = "STEP_OUT_OF_RANGE"
    TERMINAL_STEP_HAS_CONTROL = "TERMINAL_STEP_HAS_CONTROL"
    WELL_NOT_ON_AXIS = "WELL_NOT_ON_AXIS"
    WELL_NOT_COMMISSIONED = "WELL_NOT_COMMISSIONED"
    SET_LRAT_ON_INJECTOR = "SET_LRAT_ON_INJECTOR"
    SET_RATE_ON_PRODUCER = "SET_RATE_ON_PRODUCER"
    CONVERT_INJ_REPEATED = "CONVERT_INJ_REPEATED"
    CONVERT_INJ_ON_INJECTOR = "CONVERT_INJ_ON_INJECTOR"
    CONFLICTING_EVENTS = "CONFLICTING_EVENTS"
    FIXED_LAYER_CHANGED = "FIXED_LAYER_CHANGED"
    WELL_OUTAGE_VIOLATED = "WELL_OUTAGE_VIOLATED"
    TARGET_UNDERSHOOT = "TARGET_UNDERSHOOT"
    BHP_BELOW_PRODUCER_LIMIT = "BHP_BELOW_PRODUCER_LIMIT"
    BHP_ABOVE_INJECTOR_LIMIT = "BHP_ABOVE_INJECTOR_LIMIT"
    MODE_NOT_REPORTED = "MODE_NOT_REPORTED"
    MODE_CONTRADICTS_SCHEDULE = "MODE_CONTRADICTS_SCHEDULE"
    BHP_LIMITED_WITHOUT_UNDERSHOOT = "BHP_LIMITED_WITHOUT_UNDERSHOOT"
    ROLE_FACT_MISMATCH = "ROLE_FACT_MISMATCH"
    OPEN_WITHOUT_FLOW = "OPEN_WITHOUT_FLOW"
    SHUT_WITH_FLOW = "SHUT_WITH_FLOW"
    NEGATIVE_INTERVAL_DELTA = "NEGATIVE_INTERVAL_DELTA"
    RESPONSE_AXIS_INCOMPLETE = "RESPONSE_AXIS_INCOMPLETE"
    LIQUID_LIMIT_EXCEEDED = "LIQUID_LIMIT_EXCEEDED"
    INJECTION_LIMIT_EXCEEDED = "INJECTION_LIMIT_EXCEEDED"
    PRODUCTION_FLOOR_MISSED = "PRODUCTION_FLOOR_MISSED"
    OIL_LIMIT_EXCEEDED = "OIL_LIMIT_EXCEEDED"
    WATERCUT_LIMIT_EXCEEDED = "WATERCUT_LIMIT_EXCEEDED"
    OUTAGE_WELL_PRODUCED = "OUTAGE_WELL_PRODUCED"
    WATER_SUPPLY_LIMIT_EXCEEDED = "WATER_SUPPLY_LIMIT_EXCEEDED"
    COMPENSATION_OUT_OF_CORRIDOR = "COMPENSATION_OUT_OF_CORRIDOR"
    COMPENSATION_UNDEFINED = "COMPENSATION_UNDEFINED"
    FIELD_PRESSURE_BELOW_FLOOR = "FIELD_PRESSURE_BELOW_FLOOR"
    FIELD_PRESSURE_ABOVE_CEILING = "FIELD_PRESSURE_ABOVE_CEILING"
    REGION_PRESSURE_BELOW_FLOOR = "REGION_PRESSURE_BELOW_FLOOR"
    REGION_PRESSURE_ABOVE_CEILING = "REGION_PRESSURE_ABOVE_CEILING"
    MATERIAL_BALANCE_BROKEN = "MATERIAL_BALANCE_BROKEN"


@dataclass(frozen=True, slots=True)
class Violation:
    kind: ViolationKind
    control_step: int | None
    well: str | None
    value: float | None
    detail: str
    region: int | None = None

    def __str__(self) -> str:
        where = []
        if self.control_step is not None:
            where.append(f"control_step={self.control_step}")
        if self.region is not None:
            where.append(f"region {self.region}")
        if self.well is not None:
            where.append(f"well {self.well!r}")
        location = ", ".join(where) if where else "schedule"
        value = "" if self.value is None else f", value {self.value!r}"
        return f"[{self.kind.value}] {location}{value}: {self.detail}"


STATUS_CHECKED: str = "checked"
STATUS_UNSUPPORTED: str = "unsupported"
STATUS_NOT_SET: str = "not_set"
STATUS_WAIVED: str = "waived"

CONSTRAINT_STATUSES: frozenset[str] = frozenset(
    {STATUS_CHECKED, STATUS_UNSUPPORTED, STATUS_NOT_SET, STATUS_WAIVED}
)

CONSTRAINT_LIQUID_LIMITS: str = "liquid_limits"
CONSTRAINT_INJECTION_LIMITS: str = "injection_limits"
CONSTRAINT_PRODUCTION_FLOORS: str = "production_floors"
CONSTRAINT_OIL_LIMITS: str = "oil_limits"
CONSTRAINT_WATERCUT_LIMITS: str = "watercut_limits"
CONSTRAINT_WELL_OUTAGES: str = "well_outages"
CONSTRAINT_WELL_OUTAGES_STATIC: str = "well_outages (static)"
CONSTRAINT_WATER_SUPPLY: str = "infrastructure.water_supply"
CONSTRAINT_COMPENSATION: str = "infrastructure.compensation"
CONSTRAINT_COMPENSATION_SCOPE: str = "infrastructure.compensation_scope"
CONSTRAINT_BHP_LIMITS: str = "infrastructure.bhp_limits"
CONSTRAINT_FIELD_PRESSURE: str = "infrastructure.field_pressure"
CONSTRAINT_REGION_PRESSURE: str = "infrastructure.region_pressure"
CONSTRAINT_MATERIAL_BALANCE: str = "material_balance"


@dataclass(frozen=True, slots=True)
class ConstraintCheck:
    constraint: str
    status: str
    kinds: tuple[ViolationKind, ...]
    n_violations: int | None
    blocking: bool
    enforcement: str | None
    detail: str

    def __post_init__(self) -> None:
        if self.status not in CONSTRAINT_STATUSES:
            raise ValueError(
                f"unknown constraint check status {self.status!r}: one of "
                f"{sorted(CONSTRAINT_STATUSES)} expected"
            )
        if self.status == STATUS_CHECKED and self.n_violations is None:
            raise ValueError(
                f"{self.constraint}: status {STATUS_CHECKED!r} must carry "
                "the number of violations, otherwise the report does not "
                "state the result of the check"
            )
        if self.status != STATUS_CHECKED and self.n_violations is not None:
            raise ValueError(
                f"{self.constraint}: status {self.status!r} means the check "
                "was not performed, so there can be no number of violations"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "constraint": self.constraint,
            "status": self.status,
            "n_violations": self.n_violations,
            "blocking": self.blocking,
            "kinds": [kind.value for kind in self.kinds],
            "enforcement": self.enforcement,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    violations: tuple[Violation, ...]
    n_control_events: int
    n_fixed_events: int
    n_intervals: int

    @property
    def ok(self) -> bool:
        return not self.violations

    def by_kind(self) -> dict[ViolationKind, tuple[Violation, ...]]:
        buckets: dict[ViolationKind, list[Violation]] = {}
        for violation in self.violations:
            buckets.setdefault(violation.kind, []).append(violation)
        return {kind: tuple(items) for kind, items in buckets.items()}

    def counts(self) -> dict[ViolationKind, int]:
        return {kind: len(items) for kind, items in self.by_kind().items()}

    def format(self, limit: int = 50) -> str:
        if self.ok:
            return (
                f"no violations: {self.n_control_events} control events, "
                f"{self.n_fixed_events} fixed, {self.n_intervals} intervals"
            )
        head = "\n".join(str(item) for item in self.violations[:limit])
        tail = (
            f"\n... {len(self.violations) - limit} more"
            if len(self.violations) > limit
            else ""
        )
        return f"violations {len(self.violations)}:\n{head}{tail}"

    def raise_if_violated(self) -> None:
        if not self.ok:
            raise StaticValidationError(self.format(), self)


class StaticValidationError(ValidationError):
    default_code = "schedule.static"

    def __init__(self, message: str, report: ValidationReport) -> None:
        super().__init__(message)
        self.report = report
