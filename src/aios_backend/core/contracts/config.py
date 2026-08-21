"""Config — воспроизводимость. README.md §10, §10a.

Правило: ни один компонент не читает параметр мимо конфига. Запуск
определяется парой «конфиг плюс данные организаторов».
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .policy import Rule


# Снято 15.08 вместе с ответами организаторов. Три политики существовали
# потому, что первая редакция Методики о них молчала; скорректированная
# редакция и эталонный расчётчик CHDD_PYTHON ответили на все три, и ветвление
# превратилось бы в возможность посчитать не так, как считает проверяющая
# сторона (docs/context/04_models.md §4.0):
#
#   TaxPolicy        -> налоги считаются всегда. FCF = EBITDA - налог на
#                       прибыль - CAPEX, ставка живёт в NormativeSet.
#   LiquidOpexPolicy -> норматив руб/т применяется к WLPT_Diff как есть.
#                       Методика объявляет WLPT_Diff массой в тоннах,
#                       пересчёт плотностью не производится.
#   InitialEspPolicy -> см. ChargeInitialEsp ниже: ветка осталась, но
#                       умолчание сменилось на противоположное.


class ChargeInitialEsp(Enum):
    """Оплачивается ли первичное оснащение фонда ЭЦН.

    Зеркалит флаг `chargeInitialPump` эталонного расчётчика. Методика:
    «На первом расчетном шаге стоимость исходно установленного ЭЦН может
    учитываться только при включении соответствующей опции расчета; по
    умолчанию первичное оснащение фонда отдельно не начисляется».

    NOT_CHARGED — то, чем считает проверяющая сторона. Ветка сохранена
    только потому, что опция существует и в кейсе может быть включена;
    менять умолчание без письменного основания от организаторов нельзя.

    Правило распространяется одинаково на 81 скважину, действующую на t0,
    и на 22 вводимые внутри горизонта: типоразмер подбирается всегда (он
    нужен храповику для верного отсчёта последующих замен), CAPEX за
    первичную установку не начисляется.
    """

    NOT_CHARGED = "NOT_CHARGED"
    CHARGED_AT_FIRST_STEP = "CHARGED_AT_FIRST_STEP"


class QuantizationPolicy(Enum):
    """Сетка допустимых уставок. Ответа организаторов нет (§3.1), ветка живая."""

    NONE = "NONE"
    STEP_5 = "STEP_5"


@dataclass(frozen=True, slots=True)
class EspCatalogEntry:
    nominal: float  # м³/сут
    interval_low: float
    interval_high: float
    cost_rub: float


@dataclass(frozen=True, slots=True)
class NormativeSet:
    """Нормативы Методики (docs/context/04_models.md §4).

    Деньги в рублях (не тысячах, не миллионах) — 1.8 млн руб/операцию из
    Методики кладётся как 1_800_000, ставки — доля, не проценты.

    Значения сверены с ../models/CHDD_PYTHON/input/Нормативы_ЧДД.xlsx.
    Источник истины — этот файл, а не выписки из текста Методики.

    Семь величин Методика запирает (METHODOLOGY_LOCKS в chdd_model.py):
    event_cost_rub, conversion_base_cost_rub, порог понижения типоразмера
    ЭЦН и четыре флага режима расчёта. Эталон перетирает поданные значения
    своими, так что подобрать их «под себя» невозможно.
    """

    price_oil_rub_per_t: float
    deductions_rub_per_t: float
    opex_oil_rub_per_t: float
    opex_liquid_rub_per_t: float
    opex_injection_rub_per_m3: float
    opex_wellstock_rub_per_well_year: float
    esp_swap_opex_rub: float  # операция смены, в OPEX; цена насоса — в CAPEX
    event_cost_rub: float
    # Полная стоимость перевода под закачку. ЭЦН к ней НЕ добавляется:
    # «Все затраты перевода учитываются в OPEX один раз», и эталонный
    # расчётчик выставляет conversionPumpCostM = 0.0. Первая редакция
    # Методики задавала OPEX_ВНС = 5.0 + C_ki^ESP — слагаемое убрано
    # 13.08 (docs/context/04_models.md §4.0 п.2).
    conversion_base_cost_rub: float
    wacc: float
    property_tax_rate: float  # входит в OPEX
    income_tax_rate: float  # входит в FCF, считается на годовой прибыли
    esp_catalog: tuple[EspCatalogEntry, ...]


# Базовые значения из докс (docs/context/04_models.md §4) — стартовая точка
# для NormativeSet.base, не подставляются нигде автоматически: конфиг
# обязан задать их явно (§11.1 базы знаний "ни один компонент не читает
# параметр мимо конфига").
DEFAULT_NORMATIVES_2007 = dict(
    price_oil_rub_per_t=28_000.0,
    deductions_rub_per_t=19_600.0,
    opex_oil_rub_per_t=40.0,
    opex_liquid_rub_per_t=100.0,
    opex_injection_rub_per_m3=30.0,
    opex_wellstock_rub_per_well_year=1_000_000.0,
    esp_swap_opex_rub=1_800_000.0,
    event_cost_rub=1_000_000.0,
    conversion_base_cost_rub=5_000_000.0,
    wacc=0.10,
    property_tax_rate=0.022,
    income_tax_rate=0.25,
)


# Годовых переопределений нормативов больше нет. Механизм `Normatives.base +
# by_year` и тип PartialNormativeSet сняты 15.08: они стояли на формулировке
# первой редакции Методики «используются как базовые и могут изменяться по
# годам в зависимости от условий сценария». Скорректированная редакция
# говорит прямо обратное — «применяются без изменения на всем расчетном
# горизонте до последнего расчетного шага», — и эталонный расчётчик читает
# ровно один скалярный набор. Ось лет у нормативов создавала бы экономику,
# которой у проверяющей стороны нет (docs/context/04_models.md §4.0 п.4).


@dataclass(frozen=True, slots=True)
class Policies:
    """Ветки, у которых ответа организаторов ещё нет либо опция существует.

    Политик было четыре, осталось две: tax_policy и liquid_opex_policy
    закрыты разбором эталонного расчётчика и превратились в единственно
    верное поведение, ветвиться там больше не по чему.
    """

    charge_initial_esp: ChargeInitialEsp
    quantization_policy: QuantizationPolicy


@dataclass(frozen=True, slots=True)
class Budgets:
    runs_per_verification_round: int
    fixed_point_iteration_cap: int


@dataclass(frozen=True, slots=True)
class ArtifactHashes:
    deck_hash: str
    history_prefix_hash: str
    summary_spec_hash: str
    groups_hash: str
    dataset_version_hash: str
    surrogate_checkpoint_hash: str


@dataclass(frozen=True, slots=True)
class Config:
    """Хеш выданного дека внутри конфига доказывает, что расчёт шёл на
    данных организаторов (§11.3 базы знаний)."""

    seeds: dict[str, int]  # "global" и по компонентам
    policies: Policies
    normatives: NormativeSet  # один скалярный набор на весь горизонт
    theta: dict[str, float]
    rules: dict[Rule, bool]
    budgets: Budgets
    hashes: ArtifactHashes
