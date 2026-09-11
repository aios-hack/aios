from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.contexts.economics.domain.errors import DecompositionError

MACHINE_ZERO_RUB: float = 1e-6
MACHINE_RELATIVE_TOLERANCE: float = 1e-12


class TaxBasis(Enum):
    BEFORE_TAX = "BEFORE_TAX"
    WITH_ALLOCATED_TAX = "WITH_ALLOCATED_TAX"


TAX_BASIS_CAPTION: dict[TaxBasis, str] = {
    TaxBasis.BEFORE_TAX: (
        "before income tax - decomposes across wells exactly"
    ),
    TaxBasis.WITH_ALLOCATED_TAX: (
        "with allocated tax - income tax is computed from the annual "
        "field profit and spread across wells by convention, proportionally to "
        "the positive contribution to the annual profit"
    ),
}


@dataclass(frozen=True, slots=True)
class IntervalPoint:
    control_step: int
    year: int
    fcf: float
    df: float
    discounted_fcf: float
    cumulative_discounted_fcf: float


@dataclass(frozen=True, slots=True)
class IntervalSeries:
    points: tuple[IntervalPoint, ...]
    n_intervals: int

    @property
    def control_steps(self) -> tuple[int, ...]:
        return tuple(point.control_step for point in self.points)

    @property
    def total_discounted_fcf(self) -> float:
        return sum(point.discounted_fcf for point in self.points)

    def by_year(self) -> dict[int, float]:
        totals: dict[int, float] = {}
        for point in self.points:
            totals[point.year] = totals.get(point.year, 0.0) + point.discounted_fcf
        return dict(sorted(totals.items()))


@dataclass(frozen=True, slots=True)
class WellContribution:
    well: str
    basis: TaxBasis
    revenue: float
    opex_total: float
    event_costs: float
    capex_esp: float
    income_tax: float
    ebitda: float
    discounted_fcf: float

    @property
    def caption(self) -> str:
        return TAX_BASIS_CAPTION[self.basis]


@dataclass(frozen=True, slots=True)
class WellRanking:
    basis: TaxBasis
    contributions: tuple[WellContribution, ...]

    @property
    def caption(self) -> str:
        return TAX_BASIS_CAPTION[self.basis]

    @property
    def total_discounted_fcf(self) -> float:
        return sum(item.discounted_fcf for item in self.contributions)

    def worst(self, count: int = 10) -> tuple[WellContribution, ...]:
        return self.contributions[:count]

    def best(self, count: int = 10) -> tuple[WellContribution, ...]:
        return tuple(reversed(self.contributions[-count:]))

    def negative(self) -> tuple[WellContribution, ...]:
        return tuple(item for item in self.contributions if item.discounted_fcf < 0.0)


@dataclass(frozen=True, slots=True)
class InvariantResidual:
    name: str
    key: int | str
    expected: float
    actual: float

    @property
    def residual(self) -> float:
        return self.actual - self.expected

    @property
    def absolute(self) -> float:
        return abs(self.residual)

    @property
    def scale(self) -> float:
        return max(abs(self.expected), abs(self.actual))

    def within(self, absolute_tolerance: float, relative_tolerance: float) -> bool:
        return self.absolute <= max(absolute_tolerance, relative_tolerance * self.scale)

    def __str__(self) -> str:
        return (
            f"{self.name}[{self.key}]: expected {self.expected!r}, got "
            f"{self.actual!r}, residual {self.residual!r}"
        )


@dataclass(frozen=True, slots=True)
class InvariantReport:
    monthly_to_annual: tuple[InvariantResidual, ...]
    per_well_to_total: tuple[InvariantResidual, ...]
    absolute_tolerance: float
    relative_tolerance: float

    @property
    def residuals(self) -> tuple[InvariantResidual, ...]:
        return self.monthly_to_annual + self.per_well_to_total

    @property
    def failures(self) -> tuple[InvariantResidual, ...]:
        return tuple(
            item
            for item in self.residuals
            if not item.within(self.absolute_tolerance, self.relative_tolerance)
        )

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def max_absolute(self) -> float:
        return max((item.absolute for item in self.residuals), default=0.0)

    def format(self) -> str:
        if self.ok:
            return (
                f"the §4 invariants hold: {len(self.residuals)} checks, "
                f"maximum residual {self.max_absolute!r} RUB"
            )
        head = "\n".join(str(item) for item in self.failures[:20])
        return f"the §4 invariants are violated: {len(self.failures)} of {len(self.residuals)}\n{head}"

    def raise_if_violated(self) -> None:
        if not self.ok:
            raise DecompositionError(self.format())
