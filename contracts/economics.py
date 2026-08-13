"""NpvTable — результат расчёта денег. README.md §4."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LineItems:
    """Статьи одной строки разложения. Все суммы в рублях, df безразмерный."""

    revenue: float
    deductions: float
    opex_oil: float
    opex_liquid: float
    opex_injection: float
    opex_wellstock: float
    event_costs: float
    capex_esp: float
    ebitda: float
    fcf: float
    df: float
    discounted_fcf: float


@dataclass(frozen=True, slots=True)
class NpvTable:
    """Три разложения плюс единственная сдаваемая величина.

    by_year: 2007…2025. by_month: control_step 0…223 (control_step=224,
    terminal_state, в разложении по месяцам отсутствует — у него нет
    интервала). by_well: идентификатор скважины.

    Инварианты (README.md §4): сумма месячных внутри года равна годовому
    дисконтированному значению с точностью до машинного нуля; сумма
    поскважинных значений равна npv_methodology без остатка.
    """

    by_year: dict[int, LineItems]
    by_month: dict[int, LineItems]  # control_step -> LineItems
    by_well: dict[str, LineItems]
    npv_methodology: float  # единственная сдаваемая величина; никакая
    # другая функция слова "npv" в имени не носит
