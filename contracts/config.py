"""Config — воспроизводимость. README.md §10, §10a.

Правило: ни один компонент не читает параметр мимо конфига. Запуск
определяется парой «конфиг плюс данные организаторов».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .policy import Rule


class TaxPolicy(Enum):
    """Считать ли налоги вообще — ветка, не ставка (04_models.md §6.1)."""

    WITH_TAXES = "WITH_TAXES"
    WITHOUT_TAXES = "WITHOUT_TAXES"


class InitialEspPolicy(Enum):
    CAPEX_AT_START = "CAPEX_AT_START"
    ALREADY_INSTALLED = "ALREADY_INSTALLED"


class QuantizationPolicy(Enum):
    NONE = "NONE"
    STEP_5 = "STEP_5"


class LiquidOpexPolicy(Enum):
    BY_VOLUME = "BY_VOLUME"
    BY_MASS_VIA_DENSITY = "BY_MASS_VIA_DENSITY"


@dataclass(frozen=True, slots=True)
class EspCatalogEntry:
    nominal: float  # м³/сут
    interval_low: float
    interval_high: float
    cost_rub: float


@dataclass(frozen=True, slots=True)
class NormativeSet:
    """Базовые значения Методики (docs/context/04_models.md §4).

    Деньги в рублях (не тысячах, не миллионах) — 1.8 млн руб/операцию из
    Методики кладётся как 1_800_000, ставки — доля, не проценты.
    """

    price_oil_rub_per_t: float
    deductions_rub_per_t: float
    opex_oil_rub_per_t: float
    opex_liquid_rub_per_t: float
    opex_injection_rub_per_m3: float
    opex_wellstock_rub_per_well_year: float
    esp_swap_opex_rub: float
    event_cost_rub: float
    conversion_base_cost_rub: float  # без стоимости ЭЦН, та отдельно из esp_catalog
    wacc: float
    property_tax_rate: float
    income_tax_rate: float
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


@dataclass(frozen=True, slots=True)
class PartialNormativeSet:
    """Те же поля, что NormativeSet, но все опциональны — только
    изменённые поля года. Остальные наследуются из normatives.base."""

    price_oil_rub_per_t: float | None = None
    deductions_rub_per_t: float | None = None
    opex_oil_rub_per_t: float | None = None
    opex_liquid_rub_per_t: float | None = None
    opex_injection_rub_per_m3: float | None = None
    opex_wellstock_rub_per_well_year: float | None = None
    esp_swap_opex_rub: float | None = None
    event_cost_rub: float | None = None
    conversion_base_cost_rub: float | None = None
    wacc: float | None = None
    property_tax_rate: float | None = None
    income_tax_rate: float | None = None
    esp_catalog: tuple[EspCatalogEntry, ...] | None = None


@dataclass(frozen=True, slots=True)
class Normatives:
    base: NormativeSet
    by_year: dict[str, PartialNormativeSet] = field(default_factory=dict)  # ключ "YYYY"

    def __post_init__(self) -> None:
        for key in self.by_year:
            if not (isinstance(key, str) and len(key) == 4 and key.isdigit()):
                raise ValueError(f'by_year ключ должен быть строкой "YYYY", получено {key!r}')

    def for_year(self, year: int) -> NormativeSet:
        """base с точечными полями by_year[year] поверх — не два
        независимых объекта для ручного мержа в каждом месте использования."""
        override = self.by_year.get(str(year))
        if override is None:
            return self.base
        merged = {
            f: (getattr(override, f) if getattr(override, f) is not None else getattr(self.base, f))
            for f in self.base.__dataclass_fields__
        }
        return NormativeSet(**merged)


@dataclass(frozen=True, slots=True)
class Policies:
    tax_policy: TaxPolicy
    initial_esp_policy: InitialEspPolicy
    quantization_policy: QuantizationPolicy
    liquid_opex_policy: LiquidOpexPolicy


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
    normatives: Normatives
    theta: dict[str, float]
    rules: dict[Rule, bool]
    budgets: Budgets
    hashes: ArtifactHashes
