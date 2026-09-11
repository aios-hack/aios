from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.contexts.economics.domain.economics import LineItems, NpvTable
from backend.contexts.economics.domain.errors import ParityError

RUB_PER_MILLION: float = 1_000_000.0

LINE_ITEM_FIELDS: tuple[str, ...] = (
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
    "income_tax",
    "fcf",
    "discounted_fcf",
)

EVENT_COST_KEYS: tuple[str, ...] = ("gtmM", "startStopCostM", "conversionOpexM")

MACHINE_RELATIVE_TOLERANCE: float = 1e-12


REFERENCE_KEY_BY_FIELD: dict[str, str] = {
    "revenue": "revenueM",
    "deductions": "deductionsM",
    "opex_oil": "oilOpexM",
    "opex_liquid": "liquidOpexM",
    "opex_injection": "injectionOpexM",
    "opex_wellstock": "fundOpexM",
    "property_tax": "propertyTaxM",
    "capex_esp": "capexM",
    "ebitda": "ebitdaM",
    "income_tax": "profitTaxM",
    "fcf": "fcfM",
    "discounted_fcf": "chddM",
}


@dataclass(frozen=True, slots=True)
class Discrepancy:
    scope: str
    key: int | str
    field: str
    ours: float
    reference: float

    @property
    def absolute(self) -> float:
        return abs(self.ours - self.reference)

    def __str__(self) -> str:
        return (
            f"{self.scope}[{self.key}].{self.field}: ours {self.ours!r} "
            f"against the reference {self.reference!r}, difference {self.absolute!r}"
        )


@dataclass(frozen=True, slots=True)
class ParityReport:
    discrepancies: tuple[Discrepancy, ...]
    npv_ours: float
    npv_reference: float
    years: tuple[int, ...]
    months: tuple[int, ...]

    @property
    def matched(self) -> bool:
        return not self.discrepancies

    @property
    def npv_absolute(self) -> float:
        return abs(self.npv_ours - self.npv_reference)

    def raise_if_mismatched(self) -> None:
        if self.matched:
            return
        head = "\n".join(str(item) for item in self.discrepancies[:20])
        raise ParityError(
            f"divergence from the reference: {len(self.discrepancies)} items, "
            f"NPV ours {self.npv_ours!r} against {self.npv_reference!r} "
            f"(difference {self.npv_absolute!r})\n{head}"
        )


def reference_line_items(entry: Mapping[str, Any]) -> LineItems:
    values = {
        field: float(entry[key]) * RUB_PER_MILLION
        for field, key in REFERENCE_KEY_BY_FIELD.items()
    }
    values["event_costs"] = (
        sum(float(entry[key]) for key in EVENT_COST_KEYS) * RUB_PER_MILLION
    )
    return LineItems(df=float(entry["discountFactor"]), **values)


def _month_index(month: str, interval_start_dates: Sequence[date]) -> int | None:
    for control_step, moment in enumerate(interval_start_dates):
        if f"{moment.year:04d}-{moment.month:02d}" == month:
            return control_step
    return None


def compare_line_items(
    scope: str,
    key: int | str,
    ours: LineItems,
    reference: LineItems,
    tolerance_rub: float,
    relative_tolerance: float,
) -> list[Discrepancy]:
    found: list[Discrepancy] = []
    for field in LINE_ITEM_FIELDS:
        our_value = float(getattr(ours, field))
        reference_value = float(getattr(reference, field))
        if field == "df":
            limit = 0.0
        else:
            scale = max(abs(our_value), abs(reference_value))
            limit = max(tolerance_rub, relative_tolerance * scale)
        if abs(our_value - reference_value) > limit:
            found.append(
                Discrepancy(
                    scope=scope,
                    key=key,
                    field=field,
                    ours=our_value,
                    reference=reference_value,
                )
            )
    return found


def compare_with_reference(
    table: NpvTable,
    reference_result: Mapping[str, Any],
    interval_start_dates: Sequence[date],
    tolerance_rub: float = 0.0,
    relative_tolerance: float = MACHINE_RELATIVE_TOLERANCE,
) -> ParityReport:
    discrepancies: list[Discrepancy] = []

    reference_by_year = {
        int(entry["year"]): reference_line_items(entry)
        for entry in reference_result["annual"]
    }
    our_years = tuple(sorted(table.by_year))
    reference_years = tuple(sorted(reference_by_year))
    if our_years != reference_years:
        raise ParityError(
            f"year axes do not match: ours {our_years}, reference {reference_years}"
        )
    for year in our_years:
        discrepancies.extend(
            compare_line_items(
                "year",
                year,
                table.by_year[year],
                reference_by_year[year],
                tolerance_rub,
                relative_tolerance,
            )
        )

    reference_by_step: dict[int, LineItems] = {}
    for entry in reference_result["fieldMonthly"]:
        control_step = _month_index(str(entry["month"]), interval_start_dates)
        if control_step is None:
            continue
        reference_by_step[control_step] = reference_line_items(entry)
    our_months = tuple(sorted(table.by_month))
    reference_months = tuple(sorted(reference_by_step))
    if our_months != reference_months:
        raise ParityError(
            f"month axes do not match: ours {our_months}, "
            f"reference {reference_months}"
        )
    for control_step in our_months:
        discrepancies.extend(
            compare_line_items(
                "month",
                control_step,
                table.by_month[control_step],
                reference_by_step[control_step],
                tolerance_rub,
                relative_tolerance,
            )
        )

    npv_reference = float(reference_result["summary"]["totalChddM"]) * RUB_PER_MILLION
    npv_limit = max(
        tolerance_rub,
        relative_tolerance * max(abs(table.npv_methodology), abs(npv_reference)),
    )
    if abs(table.npv_methodology - npv_reference) > npv_limit:
        discrepancies.append(
            Discrepancy(
                scope="total",
                key="npv_methodology",
                field="npv_methodology",
                ours=table.npv_methodology,
                reference=npv_reference,
            )
        )

    return ParityReport(
        discrepancies=tuple(discrepancies),
        npv_ours=table.npv_methodology,
        npv_reference=npv_reference,
        years=our_years,
        months=our_months,
    )
