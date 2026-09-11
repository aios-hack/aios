from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from backend.core.contracts import LineItems, NpvTable

from .npv import (
    DISCOUNT_BASE_YEAR,
    CellFlows,
    allocate_income_tax,
    discount_factor,
)

MACHINE_ZERO_RUB: float = 1e-6
MACHINE_RELATIVE_TOLERANCE: float = 1e-12


class DecompositionError(ValueError):
    pass


class TaxBasis(Enum):
    BEFORE_TAX = "BEFORE_TAX"
    WITH_ALLOCATED_TAX = "WITH_ALLOCATED_TAX"


TAX_BASIS_CAPTION: dict[TaxBasis, str] = {
    TaxBasis.BEFORE_TAX: (
        "до налога на прибыль — раскладывается по скважинам точно"
    ),
    TaxBasis.WITH_ALLOCATED_TAX: (
        "с распределённым налогом — налог на прибыль считается от годовой "
        "прибыли поля и разнесён по скважинам соглашением, пропорционально "
        "положительному вкладу в годовую прибыль"
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
            f"{self.name}[{self.key}]: ожидалось {self.expected!r}, получено "
            f"{self.actual!r}, невязка {self.residual!r}"
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
                f"инварианты §4 соблюдены: {len(self.residuals)} проверок, "
                f"максимальная невязка {self.max_absolute!r} руб"
            )
        head = "\n".join(str(item) for item in self.failures[:20])
        return f"нарушены инварианты §4: {len(self.failures)} из {len(self.residuals)}\n{head}"

    def raise_if_violated(self) -> None:
        if not self.ok:
            raise DecompositionError(self.format())


def interval_series(table: NpvTable, interval_years: Sequence[int]) -> IntervalSeries:
    steps = sorted(table.by_month)
    if steps and max(steps) >= len(interval_years):
        raise DecompositionError(
            f"ряд по интервалам ссылается на шаг {max(steps)} при "
            f"{len(interval_years)} годах интервалов"
        )
    points: list[IntervalPoint] = []
    running = 0.0
    for control_step in steps:
        item = table.by_month[control_step]
        running += item.discounted_fcf
        points.append(
            IntervalPoint(
                control_step=control_step,
                year=interval_years[control_step],
                fcf=item.fcf,
                df=item.df,
                discounted_fcf=item.discounted_fcf,
                cumulative_discounted_fcf=running,
            )
        )
    return IntervalSeries(points=tuple(points), n_intervals=len(interval_years))


def _opex_total(item: LineItems) -> float:
    return (
        item.opex_oil
        + item.opex_liquid
        + item.opex_injection
        + item.opex_wellstock
        + item.property_tax
        + item.event_costs
    )


def check_monthly_to_annual(
    table: NpvTable, interval_years: Sequence[int]
) -> tuple[InvariantResidual, ...]:
    months_by_year: dict[int, list[int]] = {}
    for control_step in sorted(table.by_month):
        if control_step >= len(interval_years):
            raise DecompositionError(
                f"месячное разложение содержит шаг {control_step} при "
                f"{len(interval_years)} годами интервалов"
            )
        months_by_year.setdefault(interval_years[control_step], []).append(control_step)
    if set(months_by_year) != set(table.by_year):
        raise DecompositionError(
            f"оси лет не совпадают: месячная {sorted(months_by_year)}, "
            f"годовая {sorted(table.by_year)}"
        )
    residuals: list[InvariantResidual] = []
    for year, steps in sorted(months_by_year.items()):
        annual = table.by_year[year]
        for name, field in (
            ("месячное↔годовое discounted_fcf", "discounted_fcf"),
            ("месячное↔годовое fcf", "fcf"),
            ("месячное↔годовое income_tax", "income_tax"),
            ("месячное↔годовое revenue", "revenue"),
            ("месячное↔годовое ebitda", "ebitda"),
        ):
            residuals.append(
                InvariantResidual(
                    name=name,
                    key=year,
                    expected=float(getattr(annual, field)),
                    actual=sum(
                        float(getattr(table.by_month[step], field)) for step in steps
                    ),
                )
            )
    return tuple(residuals)


EXACT_PER_WELL_FIELDS: tuple[str, ...] = (
    "revenue",
    "deductions",
    "opex_oil",
    "opex_liquid",
    "opex_injection",
    "opex_wellstock",
    "property_tax",
    "event_costs",
    "capex_esp",
    "ebitda",
)


def check_per_well_to_total(table: NpvTable) -> tuple[InvariantResidual, ...]:
    residuals: list[InvariantResidual] = [
        InvariantResidual(
            name="поскважинное↔полный ЧДД",
            key="npv_methodology",
            expected=table.npv_methodology,
            actual=sum(item.discounted_fcf for item in table.by_well.values()),
        )
    ]
    for field in EXACT_PER_WELL_FIELDS:
        residuals.append(
            InvariantResidual(
                name=f"поскважинное↔годовое {field}",
                key=field,
                expected=sum(
                    float(getattr(item, field)) for item in table.by_year.values()
                ),
                actual=sum(
                    float(getattr(item, field)) for item in table.by_well.values()
                ),
            )
        )
    residuals.append(
        InvariantResidual(
            name="поскважинное↔годовое income_tax (соглашение)",
            key="income_tax",
            expected=sum(item.income_tax for item in table.by_year.values()),
            actual=sum(item.income_tax for item in table.by_well.values()),
        )
    )
    return tuple(residuals)


def check_invariants(
    table: NpvTable,
    interval_years: Sequence[int],
    absolute_tolerance: float = MACHINE_ZERO_RUB,
    relative_tolerance: float = MACHINE_RELATIVE_TOLERANCE,
) -> InvariantReport:
    return InvariantReport(
        monthly_to_annual=check_monthly_to_annual(table, interval_years),
        per_well_to_total=check_per_well_to_total(table),
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    )


def annual_income_tax_by_well(
    flows: Sequence[CellFlows], income_tax_rate: float
) -> dict[tuple[int, str], float]:
    profits_by_year_well: dict[int, dict[str, float]] = {}
    for cell in flows:
        by_well = profits_by_year_well.setdefault(cell.year, {})
        by_well[cell.well] = by_well.get(cell.well, 0.0) + cell.taxable_profit
    allocated: dict[tuple[int, str], float] = {}
    for year, by_well in profits_by_year_well.items():
        wells = sorted(by_well)
        shares = allocate_income_tax(
            [by_well[well] for well in wells], income_tax_rate
        )
        for well, share in zip(wells, shares):
            allocated[(year, well)] = share
    return allocated


def well_contributions_from_flows(
    flows: Sequence[CellFlows],
    income_tax_rate: float,
    wacc: float,
    discount_base_year: int,
    basis: TaxBasis,
) -> WellRanking:
    tax_by_year_well = (
        annual_income_tax_by_well(flows, income_tax_rate)
        if basis is TaxBasis.WITH_ALLOCATED_TAX
        else {}
    )
    totals: dict[str, dict[str, float]] = {}
    for cell in flows:
        bucket = totals.setdefault(
            cell.well,
            {
                "revenue": 0.0,
                "opex_total": 0.0,
                "event_costs": 0.0,
                "capex_esp": 0.0,
                "income_tax": 0.0,
                "ebitda": 0.0,
                "discounted_fcf": 0.0,
            },
        )
        df = discount_factor(cell.year, wacc, discount_base_year)
        bucket["revenue"] += cell.revenue
        bucket["opex_total"] += cell.opex_total
        bucket["event_costs"] += cell.event_costs
        bucket["capex_esp"] += cell.capex_esp
        bucket["ebitda"] += cell.ebitda
        bucket["discounted_fcf"] += (cell.ebitda - cell.capex_esp) * df

    for (year, well), tax in tax_by_year_well.items():
        bucket = totals.get(well)
        if bucket is None:
            continue
        df = discount_factor(year, wacc, discount_base_year)
        bucket["income_tax"] += tax
        bucket["discounted_fcf"] -= tax * df

    contributions = tuple(
        WellContribution(
            well=well,
            basis=basis,
            revenue=bucket["revenue"],
            opex_total=bucket["opex_total"],
            event_costs=bucket["event_costs"],
            capex_esp=bucket["capex_esp"],
            income_tax=bucket["income_tax"],
            ebitda=bucket["ebitda"],
            discounted_fcf=bucket["discounted_fcf"],
        )
        for well, bucket in totals.items()
    )
    return WellRanking(
        basis=basis,
        contributions=tuple(
            sorted(contributions, key=lambda item: (item.discounted_fcf, item.well))
        ),
    )


def well_ranking(table: NpvTable) -> WellRanking:
    contributions = tuple(
        WellContribution(
            well=well,
            basis=TaxBasis.WITH_ALLOCATED_TAX,
            revenue=item.revenue,
            opex_total=_opex_total(item),
            event_costs=item.event_costs,
            capex_esp=item.capex_esp,
            income_tax=item.income_tax,
            ebitda=item.ebitda,
            discounted_fcf=item.discounted_fcf,
        )
        for well, item in table.by_well.items()
    )
    return WellRanking(
        basis=TaxBasis.WITH_ALLOCATED_TAX,
        contributions=tuple(
            sorted(contributions, key=lambda item: (item.discounted_fcf, item.well))
        ),
    )


@dataclass(frozen=True, slots=True)
class NpvDecomposition:
    table: NpvTable
    series: IntervalSeries
    invariants: InvariantReport
    before_tax: WellRanking
    with_allocated_tax: WellRanking

    @property
    def npv_methodology(self) -> float:
        return self.table.npv_methodology

    def ranking(self, basis: TaxBasis) -> WellRanking:
        return (
            self.before_tax
            if basis is TaxBasis.BEFORE_TAX
            else self.with_allocated_tax
        )


def decompose(
    table: NpvTable,
    interval_years: Sequence[int],
    flows: Sequence[CellFlows],
    income_tax_rate: float,
    wacc: float,
    discount_base_year: int = DISCOUNT_BASE_YEAR,
    absolute_tolerance: float = MACHINE_ZERO_RUB,
    relative_tolerance: float = MACHINE_RELATIVE_TOLERANCE,
) -> NpvDecomposition:
    before_tax = well_contributions_from_flows(
        flows, income_tax_rate, wacc, discount_base_year, TaxBasis.BEFORE_TAX
    )
    with_allocated_tax = well_contributions_from_flows(
        flows,
        income_tax_rate,
        wacc,
        discount_base_year,
        TaxBasis.WITH_ALLOCATED_TAX,
    )
    return NpvDecomposition(
        table=table,
        series=interval_series(table, interval_years),
        invariants=check_invariants(
            table, interval_years, absolute_tolerance, relative_tolerance
        ),
        before_tax=before_tax,
        with_allocated_tax=with_allocated_tax,
    )
