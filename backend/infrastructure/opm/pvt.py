from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path

_PROPS_INCLUDE = "Model_Z_props.inc"
_REPEAT_RE = re.compile(r"^(\d+)\*(.*)$")
_KEYWORD_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

PVTO = "PVTO"
PVTW = "PVTW"
DENSITY = "DENSITY"


class PvtError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    return line.split("--", 1)[0].strip()


def _expand_token(token: str) -> list[str]:
    match = _REPEAT_RE.match(token)
    if match is None:
        return [token]
    count = int(match.group(1))
    value = match.group(2)
    if count <= 0:
        raise PvtError(f"повторитель {token!r}: количество должно быть больше нуля")
    if not value:
        raise PvtError(f"повторитель {token!r}: не указано повторяемое значение")
    return [value] * count


def _expand_tokens(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(_expand_token(token))
    return expanded


def _as_float(token: str, keyword: str) -> float:
    try:
        return float(token)
    except ValueError as error:
        raise PvtError(f"{keyword}: {token!r} не является числом") from error


def _keyword_records(
    text: str, keyword: str, source: Path | str
) -> list[tuple[float, ...]]:
    lines = text.splitlines()
    starts = [
        index for index, line in enumerate(lines) if _strip_comment(line) == keyword
    ]
    if not starts:
        raise PvtError(f"{source}: ключевое слово {keyword} отсутствует в деке")
    if len(starts) > 1:
        raise PvtError(f"{source}: ожидался один блок {keyword}, найдено {len(starts)}")
    records: list[tuple[float, ...]] = []
    pending: list[str] = []
    for line in lines[starts[0] + 1 :]:
        body = _strip_comment(line)
        if not body:
            continue
        if _KEYWORD_RE.match(body):
            break
        terminated = body.endswith("/")
        if terminated:
            body = body[:-1].strip()
        pending.extend(_expand_tokens(body.split()))
        if not terminated:
            continue
        records.append(tuple(_as_float(token, keyword) for token in pending))
        pending = []
    if pending:
        raise PvtError(f"{source}: блок {keyword} не закрыт '/': {pending}")
    if not records:
        raise PvtError(f"{source}: блок {keyword} не содержит записей")
    return records


@dataclass(frozen=True, slots=True)
class OilBranch:
    rs: float
    pressure_bar: tuple[float, ...]
    formation_volume_factor: tuple[float, ...]
    viscosity_cp: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class OilTable:
    branches: tuple[OilBranch, ...]

    @property
    def saturation_pressure_bar(self) -> float:
        return self.branches[0].pressure_bar[0]

    @property
    def saturated_rs(self) -> float:
        return self.branches[0].rs

    @property
    def pressure_bar(self) -> tuple[float, ...]:
        return self.branches[0].pressure_bar

    def formation_volume_factor_at(self, pressure_bar: float) -> float:
        branch = self.branches[0]
        return _interpolate(
            branch.pressure_bar,
            branch.formation_volume_factor,
            pressure_bar,
            "PVTO B_o",
        )

    def viscosity_at(self, pressure_bar: float) -> float:
        branch = self.branches[0]
        return _interpolate(
            branch.pressure_bar, branch.viscosity_cp, pressure_bar, "PVTO mu_o"
        )

    def gas_oil_ratio_at(self, pressure_bar: float) -> float:
        pressures = tuple(branch.pressure_bar[0] for branch in self.branches)
        values = tuple(branch.rs for branch in self.branches)
        return _interpolate(pressures, values, pressure_bar, "PVTO Rs")


@dataclass(frozen=True, slots=True)
class WaterTable:
    reference_pressure_bar: float
    formation_volume_factor_ref: float
    compressibility_per_bar: float
    viscosity_cp: float
    viscosibility_per_bar: float

    def formation_volume_factor_at(self, pressure_bar: float) -> float:
        if pressure_bar < 0.0:
            raise PvtError(f"PVTW B_w: давление {pressure_bar} бар отрицательно")
        delta = self.compressibility_per_bar * (
            pressure_bar - self.reference_pressure_bar
        )
        return self.formation_volume_factor_ref / (1.0 + delta + 0.5 * delta * delta)

    def viscosity_at(self, pressure_bar: float) -> float:
        if pressure_bar < 0.0:
            raise PvtError(f"PVTW mu_w: давление {pressure_bar} бар отрицательно")
        delta = self.viscosibility_per_bar * (
            pressure_bar - self.reference_pressure_bar
        )
        return self.viscosity_cp / (1.0 + delta + 0.5 * delta * delta)


@dataclass(frozen=True, slots=True)
class Densities:
    oil_kg_per_m3: float
    water_kg_per_m3: float
    gas_kg_per_m3: float


@dataclass(frozen=True, slots=True)
class PvtRegion:
    pvtnum: int
    oil: OilTable
    water: WaterTable
    density: Densities

    def oil_formation_volume_factor(self, pressure_bar: float) -> float:
        return self.oil.formation_volume_factor_at(pressure_bar)

    def water_formation_volume_factor(self, pressure_bar: float) -> float:
        return self.water.formation_volume_factor_at(pressure_bar)


@dataclass(frozen=True, slots=True)
class PvtTables:
    source: Path
    regions: tuple[PvtRegion, ...]

    @property
    def region_count(self) -> int:
        return len(self.regions)

    def region(self, pvtnum: int = 1) -> PvtRegion:
        for item in self.regions:
            if item.pvtnum == pvtnum:
                return item
        available = ", ".join(str(item.pvtnum) for item in self.regions)
        raise PvtError(
            f"{self.source}: PVT-регион {pvtnum} отсутствует; доступны: {available}"
        )

    def oil_formation_volume_factor(
        self, pressure_bar: float, pvtnum: int = 1
    ) -> float:
        return self.region(pvtnum).oil_formation_volume_factor(pressure_bar)

    def water_formation_volume_factor(
        self, pressure_bar: float, pvtnum: int = 1
    ) -> float:
        return self.region(pvtnum).water_formation_volume_factor(pressure_bar)


def _interpolate(
    xs: tuple[float, ...], ys: tuple[float, ...], x: float, label: str
) -> float:
    if not xs:
        raise PvtError(f"{label}: таблица пуста, интерполировать нечего")
    if len(xs) != len(ys):
        raise PvtError(f"{label}: длины столбцов не совпадают ({len(xs)} и {len(ys)})")
    if x < xs[0] or x > xs[-1]:
        raise PvtError(
            f"{label}: давление {x} бар вне таблицы {xs[0]}…{xs[-1]} бар; "
            "экстраполяция не выполняется"
        )
    index = bisect_left(xs, x)
    if xs[index] == x:
        return ys[index]
    left = index - 1
    span = xs[index] - xs[left]
    if span <= 0.0:
        raise PvtError(f"{label}: давление в таблице не возрастает при {x} бар")
    weight = (x - xs[left]) / span
    return ys[left] + weight * (ys[index] - ys[left])


def _parse_oil_tables(text: str, source: Path | str) -> tuple[OilTable, ...]:
    records = _keyword_records(text, PVTO, source)
    tables: list[OilTable] = []
    branches: list[OilBranch] = []
    rs: float | None = None
    pressures: list[float] = []
    factors: list[float] = []
    viscosities: list[float] = []

    def close_branch() -> None:
        nonlocal rs, pressures, factors, viscosities
        if rs is None:
            return
        if not pressures:
            raise PvtError(f"{source}: PVTO: ветвь Rs={rs} не содержит точек")
        branches.append(
            OilBranch(
                rs=rs,
                pressure_bar=tuple(pressures),
                formation_volume_factor=tuple(factors),
                viscosity_cp=tuple(viscosities),
            )
        )
        rs = None
        pressures = []
        factors = []
        viscosities = []

    for record in records:
        values = record
        if not values:
            close_branch()
            if not branches:
                raise PvtError(f"{source}: PVTO: регион не содержит ветвей Rs")
            tables.append(OilTable(branches=tuple(branches)))
            branches = []
            continue
        if len(values) % 3 == 1:
            close_branch()
            rs = values[0]
            values = values[1:]
        elif rs is None:
            raise PvtError(
                f"{source}: PVTO: точка без объявленного газосодержания Rs: {values}"
            )
        if len(values) % 3 != 0:
            raise PvtError(
                f"{source}: PVTO: запись не кратна тройке (p, B_o, mu_o): {values}"
            )
        for offset in range(0, len(values), 3):
            pressures.append(values[offset])
            factors.append(values[offset + 1])
            viscosities.append(values[offset + 2])
    close_branch()
    if branches:
        raise PvtError(f"{source}: PVTO: последний регион не закрыт пустой записью '/'")
    if not tables:
        raise PvtError(f"{source}: PVTO не содержит ни одного региона")
    return tuple(tables)


def _parse_water_tables(text: str, source: Path | str) -> tuple[WaterTable, ...]:
    records = _keyword_records(text, PVTW, source)
    tables: list[WaterTable] = []
    for values in records:
        if len(values) < 4:
            raise PvtError(
                f"{source}: PVTW: запись должна содержать не менее четырёх чисел "
                f"(pref, B_w, c_w, mu_w), получено {len(values)}: {values}"
            )
        tables.append(
            WaterTable(
                reference_pressure_bar=values[0],
                formation_volume_factor_ref=values[1],
                compressibility_per_bar=values[2],
                viscosity_cp=values[3],
                viscosibility_per_bar=values[4] if len(values) > 4 else 0.0,
            )
        )
    return tuple(tables)


def _parse_densities(text: str, source: Path | str) -> tuple[Densities, ...]:
    records = _keyword_records(text, DENSITY, source)
    tables: list[Densities] = []
    for values in records:
        if len(values) != 3:
            raise PvtError(
                f"{source}: DENSITY: запись должна содержать три числа "
                f"(нефть, вода, газ), получено {len(values)}: {values}"
            )
        tables.append(
            Densities(
                oil_kg_per_m3=values[0],
                water_kg_per_m3=values[1],
                gas_kg_per_m3=values[2],
            )
        )
    return tuple(tables)


def parse_pvt(text: str, source: Path | str = "<текст>") -> PvtTables:
    oil = _parse_oil_tables(text, source)
    water = _parse_water_tables(text, source)
    density = _parse_densities(text, source)
    counts = {PVTO: len(oil), PVTW: len(water), DENSITY: len(density)}
    if len(set(counts.values())) != 1:
        detail = ", ".join(f"{key}={value}" for key, value in counts.items())
        raise PvtError(
            f"{source}: число PVT-регионов расходится между ключевыми словами: {detail}"
        )
    regions = tuple(
        PvtRegion(pvtnum=index, oil=oil_table, water=water_table, density=density_row)
        for index, (oil_table, water_table, density_row) in enumerate(
            zip(oil, water, density), start=1
        )
    )
    return PvtTables(source=Path(source), regions=regions)


def load_pvt(model_dir: Path | str) -> PvtTables:
    props_path = Path(model_dir).resolve() / _PROPS_INCLUDE
    if not props_path.is_file():
        raise FileNotFoundError(f"PVT: файл свойств дека не найден: {props_path}")
    text = props_path.read_text(encoding="utf-8-sig")
    return parse_pvt(text, props_path)
