from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from contracts import EspCatalogEntry, NormativeSet

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
                f"{self.path}: нормативы без хеша файла не доказывают, "
                f"что расчёт шёл на данных организаторов"
            )
        if len(self.content_hash) != 64:
            raise ValueError(
                f"{self.path}: хеш длиной {len(self.content_hash)}, ожидается 64"
            )

    def load(self, loader: NormativesLoader) -> NormativeSet:
        return loader(self.path)


def _esp_catalog(rows: object) -> tuple[EspCatalogEntry, ...]:
    if rows is None:
        return ()
    if not isinstance(rows, (list, tuple)):
        raise ValueError("esp_catalog подан не списком записей")
    catalog: list[EspCatalogEntry] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("запись esp_catalog подана не отображением")
        missing = {"nominal", "interval_low", "interval_high", "cost_rub"} - set(row)
        if missing:
            raise ValueError(f"запись esp_catalog без полей {sorted(missing)}")
        entry = EspCatalogEntry(
            nominal=float(row["nominal"]),
            interval_low=float(row["interval_low"]),
            interval_high=float(row["interval_high"]),
            cost_rub=float(row["cost_rub"]),
        )
        if entry.interval_low > entry.interval_high:
            raise ValueError(
                f"ЭЦН {entry.nominal}: интервал "
                f"[{entry.interval_low}, {entry.interval_high}] пуст"
            )
        catalog.append(entry)
    return tuple(catalog)


def normatives_from_mapping(raw: Mapping[str, object]) -> NormativeSet:
    missing = set(NORMATIVE_FIELDS) - set(raw)
    if missing:
        raise ValueError(
            f"нормативы заданы не полностью, нет полей {sorted(missing)}: "
            f"умолчаний у нормативов нет, конфиг обязан задать их явно"
        )
    unknown = set(raw) - set(NORMATIVE_FIELDS) - {"esp_catalog"}
    if unknown:
        raise ValueError(f"незаявленные нормативы: {sorted(unknown)}")
    values: dict[str, float] = {}
    for name in NORMATIVE_FIELDS:
        value = float(raw[name])  # type: ignore[arg-type]
        if value < 0.0:
            raise ValueError(f"{name}={value}: отрицательный норматив")
        if name in _RATE_FIELDS and value > 1.0:
            raise ValueError(
                f"{name}={value} подан процентами: ставки кладутся долей, "
                f"25% это 0.25"
            )
        values[name] = value
    return NormativeSet(esp_catalog=_esp_catalog(raw.get("esp_catalog")), **values)
