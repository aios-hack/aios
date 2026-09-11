from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from backend.contexts.constraints.domain.config import EspCatalogEntry, NormativeSet

NORMATIVE_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(NormativeSet) if f.name != "esp_catalog"
)

_RATE_FIELDS: frozenset[str] = frozenset(
    {"wacc", "property_tax_rate", "income_tax_rate"}
)

METHODOLOGY_LOCKED: tuple[str, ...] = (
    "event_cost_rub",
    "conversion_base_cost_rub",
)


@runtime_checkable
class NormativesLoader(Protocol):
    def __call__(self, source: Path) -> NormativeSet: ...


@dataclass(frozen=True, slots=True)
class NormativeSource:
    path: Path
    content_hash: str

    def __post_init__(self) -> None:
        if not self.content_hash:
            raise ValueError(
                f"{self.path}: normatives without a file hash do not prove that the "
                f"computation ran on the organizers' data"
            )
        if len(self.content_hash) != 64:
            raise ValueError(
                f"{self.path}: hash of length {len(self.content_hash)}, 64 expected"
            )

    def load(self, loader: NormativesLoader) -> NormativeSet:
        return loader(self.path)


def _esp_catalog(rows: object) -> tuple[EspCatalogEntry, ...]:
    if rows is None:
        return ()
    if not isinstance(rows, (list, tuple)):
        raise ValueError("esp_catalog is not given as a list of entries")
    catalog: list[EspCatalogEntry] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("an esp_catalog entry is not given as a mapping")
        missing = {"nominal", "interval_low", "interval_high", "cost_rub"} - set(row)
        if missing:
            raise ValueError(f"an esp_catalog entry is missing the fields {sorted(missing)}")
        entry = EspCatalogEntry(
            nominal=float(row["nominal"]),
            interval_low=float(row["interval_low"]),
            interval_high=float(row["interval_high"]),
            cost_rub=float(row["cost_rub"]),
        )
        if entry.interval_low > entry.interval_high:
            raise ValueError(
                f"ESP {entry.nominal}: the interval "
                f"[{entry.interval_low}, {entry.interval_high}] is empty"
            )
        catalog.append(entry)
    return tuple(catalog)


def normatives_from_mapping(raw: Mapping[str, object]) -> NormativeSet:
    missing = set(NORMATIVE_FIELDS) - set(raw)
    if missing:
        raise ValueError(
            f"the normatives are incomplete, the fields {sorted(missing)} are "
            f"missing: normatives have no defaults, the config must set them "
            f"explicitly"
        )
    unknown = set(raw) - set(NORMATIVE_FIELDS) - {"esp_catalog"}
    if unknown:
        raise ValueError(f"undeclared normatives: {sorted(unknown)}")
    values: dict[str, float] = {}
    for name in NORMATIVE_FIELDS:
        value = float(raw[name])  # type: ignore[arg-type]
        if value < 0.0:
            raise ValueError(f"{name}={value}: negative normative")
        if name in _RATE_FIELDS and value > 1.0:
            raise ValueError(
                f"{name}={value} is given in percent: rates are stored as fractions, "
                f"25% is 0.25"
            )
        values[name] = value
    return NormativeSet(esp_catalog=_esp_catalog(raw.get("esp_catalog")), **values)
