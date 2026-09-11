from __future__ import annotations

from collections.abc import Sequence

from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.errors import DecompositionError
from backend.contexts.economics.domain.decomposition.types import (
    InvariantReport,
    InvariantResidual,
    IntervalPoint,
    IntervalSeries,
    MACHINE_RELATIVE_TOLERANCE,
    MACHINE_ZERO_RUB,
)


def interval_series(table: NpvTable, interval_years: Sequence[int]) -> IntervalSeries:
    steps = sorted(table.by_month)
    if steps and max(steps) >= len(interval_years):
        raise DecompositionError(
            f"the interval series references step {max(steps)} against "
            f"{len(interval_years)} interval years"
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
                f"the monthly decomposition contains step {control_step} against "
                f"{len(interval_years)} interval years"
            )
        months_by_year.setdefault(interval_years[control_step], []).append(control_step)
    if set(months_by_year) != set(table.by_year):
        raise DecompositionError(
            f"year axes do not match: monthly {sorted(months_by_year)}, "
            f"annual {sorted(table.by_year)}"
        )
    residuals: list[InvariantResidual] = []
    for year, steps in sorted(months_by_year.items()):
        annual = table.by_year[year]
        for name, field in (
            ("monthly<->annual discounted_fcf", "discounted_fcf"),
            ("monthly<->annual fcf", "fcf"),
            ("monthly<->annual income_tax", "income_tax"),
            ("monthly<->annual revenue", "revenue"),
            ("monthly<->annual ebitda", "ebitda"),
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
            name="per-well<->full NPV",
            key="npv_methodology",
            expected=table.npv_methodology,
            actual=sum(item.discounted_fcf for item in table.by_well.values()),
        )
    ]
    for field in EXACT_PER_WELL_FIELDS:
        residuals.append(
            InvariantResidual(
                name=f"per-well<->annual {field}",
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
            name="per-well<->annual income_tax (convention)",
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
