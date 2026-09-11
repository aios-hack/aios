from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.contexts.policy.domain.policy import Rule


class ChargeInitialEsp(Enum):

    NOT_CHARGED = "NOT_CHARGED"
    CHARGED_AT_FIRST_STEP = "CHARGED_AT_FIRST_STEP"


class QuantizationPolicy(Enum):

    NONE = "NONE"
    STEP_5 = "STEP_5"


@dataclass(frozen=True, slots=True)
class EspCatalogEntry:
    nominal: float
    interval_low: float
    interval_high: float
    cost_rub: float


@dataclass(frozen=True, slots=True)
class NormativeSet:

    price_oil_rub_per_t: float
    deductions_rub_per_t: float
    opex_oil_rub_per_t: float
    opex_liquid_rub_per_t: float
    opex_injection_rub_per_m3: float
    opex_wellstock_rub_per_well_year: float
    esp_swap_opex_rub: float
    event_cost_rub: float
    conversion_base_cost_rub: float
    wacc: float
    property_tax_rate: float
    income_tax_rate: float
    esp_catalog: tuple[EspCatalogEntry, ...]


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
class Policies:

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

    seeds: dict[str, int]
    policies: Policies
    normatives: NormativeSet
    theta: dict[str, float]
    rules: dict[Rule, bool]
    budgets: Budgets
    hashes: ArtifactHashes
