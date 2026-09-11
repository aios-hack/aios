"""NpvTable — результат расчёта денег. README.md §4."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LineItems:
    """Статьи одной строки разложения. Все суммы в рублях, df безразмерный.

    Цепочка (docs/context/08_contracts.md §3.4, скорректированная Методика):

        прибыль_до_налога = revenue - opex_total - amortization
                            - deductions - other_included - other_excluded
        income_tax        = max(0, прибыль_до_налога_за_год) * ставка
        ebitda            = revenue - opex_total - deductions - other_included
        fcf               = ebitda - income_tax - capex_esp
        discounted_fcf    = fcf * df

    где opex_total включает property_tax: налог на имущество — статья OPEX,
    а не отдельное вычитание после EBITDA.

    **income_tax считается на годовой базе, не на месячной.** Годовой налог
    равен max(0, сумма месячных прибылей года) * ставка и разносится по
    месяцам пропорционально положительной месячной прибыли; месяц с убытком
    несёт ноль. Помесячный расчёт с последующим суммированием даёт другое
    число на любом годе, где хотя бы один месяц убыточен. Убыток года не
    переносится на следующий — allowTaxShield заперт Методикой.
    """

    revenue: float
    deductions: float
    opex_oil: float
    opex_liquid: float
    opex_injection: float
    opex_wellstock: float
    property_tax: float  # 2.2% от средней остаточной стоимости, статья OPEX
    event_costs: float  # остановки, запуски, переводы, операции смены ЭЦН
    capex_esp: float  # цена новых насосов; первичное оснащение не входит
    ebitda: float
    income_tax: float  # 25% от годовой прибыли, разнесённые на эту строку
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

    **Оговорка по by_well.** Все статьи, кроме income_tax, скважинного
    уровня и раскладываются точно. Налог на прибыль считается от годовой
    прибыли всего поля, скважинного значения у него не существует, и в
    by_well он распределяется соглашением — пропорционально положительному
    вкладу скважины в годовую прибыль. Ранжирование скважин между собой это
    не искажает (множитель для всех положительных вкладов один), но
    потребитель, показывающий поскважинный вклад человеку, обязан подписать,
    что показывает: до налога (точно) или с распределённым налогом
    (соглашение). См. docs/context/08_contracts.md §3.3.
    """

    by_year: dict[int, LineItems]
    by_month: dict[int, LineItems]  # control_step -> LineItems
    by_well: dict[str, LineItems]
    npv_methodology: float  # единственная сдаваемая величина; никакая
    # другая функция слова "npv" в имени не носит
