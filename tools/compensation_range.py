from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.core.contracts import IntervalResponse, N_INTERVALS, T0
from backend.core.paths import data_root
from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.schedule.domain.validate_dynamic import (
    COMPENSATION_RESERVOIR_CONDITIONS,
    COMPENSATION_SURFACE_CONDITIONS,
    control_step_pressures,
    reservoir_step_totals,
)
from backend.contexts.simulation.application.baseline_diagnostics import _read_field_series
from backend.contexts.reservoir.infrastructure.pvt import PvtTables, load_pvt

DEFAULT_RESPONSE: Path = data_root() / "base_case" / "response.json"
DEFAULT_ARTIFACT: Path = data_root() / "compensation-base.json"
DEFAULT_PVTNUM: int = 1


class CompensationRangeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StepCompensation:
    control_step: int
    year: int
    withdrawal_m3: float
    injection_m3: float
    value: float


@dataclass(frozen=True, slots=True)
class Distribution:
    minimum: float
    p05: float
    median: float
    p95: float
    maximum: float
    mean: float
    n_steps: int


@dataclass(frozen=True, slots=True)
class CompensationRange:
    conditions: str
    steps: tuple[StepCompensation, ...]
    distribution: Distribution
    by_year: tuple[tuple[int, Distribution], ...]


def year_of_control_step(control_step: int) -> int:
    month_index = T0.month - 1 + control_step
    return T0.year + month_index // 12


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    if not ordered:
        raise CompensationRangeError(
            "распределение компенсации пусто: перцентиль считать не по чему"
        )
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + weight * (ordered[upper] - ordered[lower])


def distribution_of(values: Sequence[float]) -> Distribution:
    if not values:
        raise CompensationRangeError(
            "распределение компенсации требует хотя бы одного шага с "
            "определённой C(k), получено ноль: посчитать нечего"
        )
    ordered = sorted(values)
    return Distribution(
        minimum=ordered[0],
        p05=_percentile(ordered, 0.05),
        median=_percentile(ordered, 0.5),
        p95=_percentile(ordered, 0.95),
        maximum=ordered[-1],
        mean=sum(ordered) / len(ordered),
        n_steps=len(ordered),
    )


def _surface_totals(
    interval_responses: Sequence[IntervalResponse],
) -> dict[int, tuple[float, float, float]]:
    totals: dict[int, tuple[float, float, float]] = {}
    for item in interval_responses:
        oil, liquid, injection = totals.get(item.control_step, (0.0, 0.0, 0.0))
        totals[item.control_step] = (
            oil + max(0.0, item.oil_mass_delta),
            liquid + max(0.0, item.liquid_volume_delta),
            injection + max(0.0, item.injection_volume_delta),
        )
    return totals


def compensation_range(
    interval_responses: Sequence[IntervalResponse],
    reservoir_factors: Sequence[tuple[float, float]] | None = None,
    oil_density_t_per_m3: float | None = None,
) -> CompensationRange:
    if not interval_responses:
        raise CompensationRangeError(
            "отклик базового прогона пуст: распределение C(k) измерять не по "
            "чему. Инструмент меряет настоящий прогон, синтетикой его "
            "подменять нельзя"
        )
    totals = _surface_totals(interval_responses)
    if reservoir_factors is None:
        conditions = COMPENSATION_SURFACE_CONDITIONS
    else:
        if oil_density_t_per_m3 is None or oil_density_t_per_m3 <= 0.0:
            raise CompensationRangeError(
                "пересчёт в пластовые условия запрошен парой (B_o, B_w), но "
                "положительная плотность нефти не передана: объём нефти в "
                "отборе по массе не восстановить"
            )
        conditions = COMPENSATION_RESERVOIR_CONDITIONS
    steps: list[StepCompensation] = []
    for control_step in sorted(totals):
        oil, liquid, injection = totals[control_step]
        if reservoir_factors is None:
            withdrawal = liquid
            injected = injection
        else:
            if control_step >= len(reservoir_factors):
                raise CompensationRangeError(
                    f"пара (B_o, B_w) для шага {control_step} не передана: "
                    f"получено {len(reservoir_factors)} пар"
                )
            oil_factor, water_factor = reservoir_factors[control_step]
            withdrawal, injected = reservoir_step_totals(
                oil,
                liquid,
                injection,
                float(oil_density_t_per_m3),
                oil_factor,
                water_factor,
            )
        if withdrawal <= 0.0:
            continue
        steps.append(
            StepCompensation(
                control_step=control_step,
                year=year_of_control_step(control_step),
                withdrawal_m3=withdrawal,
                injection_m3=injected,
                value=injected / withdrawal,
            )
        )
    if not steps:
        raise CompensationRangeError(
            f"ни на одном из {len(totals)} шагов отбор не положителен: "
            "компенсация C(k) не определена нигде, распределения нет"
        )
    by_year: dict[int, list[float]] = {}
    for step in steps:
        by_year.setdefault(step.year, []).append(step.value)
    return CompensationRange(
        conditions=conditions,
        steps=tuple(steps),
        distribution=distribution_of([step.value for step in steps]),
        by_year=tuple(
            (year, distribution_of(by_year[year])) for year in sorted(by_year)
        ),
    )


def _distribution_payload(distribution: Distribution) -> dict[str, float | int]:
    return {
        "min": distribution.minimum,
        "p05": distribution.p05,
        "median": distribution.median,
        "p95": distribution.p95,
        "max": distribution.maximum,
        "mean": distribution.mean,
        "n_steps": distribution.n_steps,
    }


def artifact_payload(
    surface: CompensationRange,
    source_run_id: str,
    response_hash: str,
    response_path: Path,
    reservoir: CompensationRange | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_run_id": source_run_id,
        "response_hash": response_hash,
        "response_path": response_path.as_posix(),
        "formula": "C(k) = сумма положительных injection_volume_delta / сумма положительных liquid_volume_delta",
        "surface": {
            "conditions": surface.conditions,
            "distribution": _distribution_payload(surface.distribution),
            "by_year": {
                str(year): _distribution_payload(item)
                for year, item in surface.by_year
            },
            "by_step": [
                {
                    "control_step": step.control_step,
                    "year": step.year,
                    "withdrawal_m3": step.withdrawal_m3,
                    "injection_m3": step.injection_m3,
                    "value": step.value,
                }
                for step in surface.steps
            ],
        },
    }
    if reservoir is None:
        payload["reservoir"] = None
        payload["reservoir_notice"] = (
            "объёмные коэффициенты B_o/B_w не переданы: пересчёт в пластовые "
            "условия не выполнялся, приведено только поверхностное значение"
        )
        return payload
    surface_by_step = {step.control_step: step.value for step in surface.steps}
    deltas = [
        (step.value - surface_by_step[step.control_step])
        / surface_by_step[step.control_step]
        for step in reservoir.steps
        if step.control_step in surface_by_step
    ]
    payload["reservoir"] = {
        "conditions": reservoir.conditions,
        "distribution": _distribution_payload(reservoir.distribution),
        "by_year": {
            str(year): _distribution_payload(item)
            for year, item in reservoir.by_year
        },
        "by_step": [
            {
                "control_step": step.control_step,
                "year": step.year,
                "withdrawal_m3": step.withdrawal_m3,
                "injection_m3": step.injection_m3,
                "value": step.value,
            }
            for step in reservoir.steps
        ],
        "relative_difference_to_surface": _distribution_payload(
            distribution_of(deltas)
        ),
    }
    return payload


def build_artifact(
    response_path: Path,
    model_dir: Path | None = None,
    field_pressure_bar: Sequence[float] | None = None,
    n_intervals: int = N_INTERVALS,
    pvtnum: int = DEFAULT_PVTNUM,
) -> dict[str, object]:
    if not response_path.is_file():
        raise CompensationRangeError(
            f"отклик базового прогона не найден: {response_path}. Коридор "
            "компенсации меряется по настоящему прогону OPM; без отклика "
            "инструмент не пишет пустой артефакт, а сообщает об ошибке"
        )
    artifact = load_response_artifact(response_path)
    surface = compensation_range(artifact.interval_response)
    reservoir: CompensationRange | None = None
    if model_dir is not None and field_pressure_bar is not None:
        tables: PvtTables = load_pvt(model_dir)
        region = tables.region(pvtnum)
        density = region.density.oil_kg_per_m3 / 1000.0
        pressures = control_step_pressures(field_pressure_bar, n_intervals)
        factors = tuple(
            (
                tables.oil_formation_volume_factor(pressure, pvtnum),
                tables.water_formation_volume_factor(pressure, pvtnum),
            )
            for pressure in pressures
        )
        reservoir = compensation_range(artifact.interval_response, factors, density)
    return artifact_payload(
        surface,
        artifact.source_run_id,
        artifact.response_hash,
        response_path,
        reservoir,
    )


def format_report(payload: dict[str, object]) -> str:
    surface = payload["surface"]
    assert isinstance(surface, dict)
    distribution = surface["distribution"]
    assert isinstance(distribution, dict)
    lines = [
        "КОРИДОР КОМПЕНСАЦИИ ПО БАЗОВОМУ ПРОГОНУ",
        f"прогон {payload['source_run_id']}",
        f"условия: {surface['conditions']}",
        (
            f"min {distribution['min']:.4f}  p05 {distribution['p05']:.4f}  "
            f"медиана {distribution['median']:.4f}  p95 {distribution['p95']:.4f}  "
            f"max {distribution['max']:.4f}  (шагов {distribution['n_steps']})"
        ),
        "",
        "по годам: год  шагов  min  медиана  max",
    ]
    by_year = surface["by_year"]
    assert isinstance(by_year, dict)
    for year in sorted(by_year, key=int):
        item = by_year[year]
        lines.append(
            f"  {year}  {item['n_steps']:>3}  {item['min']:.4f}  "
            f"{item['median']:.4f}  {item['max']:.4f}"
        )
    reservoir = payload.get("reservoir")
    if reservoir is None:
        lines.append("")
        lines.append(str(payload.get("reservoir_notice", "")))
        return "\n".join(lines)
    assert isinstance(reservoir, dict)
    reservoir_distribution = reservoir["distribution"]
    assert isinstance(reservoir_distribution, dict)
    difference = reservoir["relative_difference_to_surface"]
    assert isinstance(difference, dict)
    lines.append("")
    lines.append(f"условия: {reservoir['conditions']}")
    lines.append(
        f"min {reservoir_distribution['min']:.4f}  "
        f"p05 {reservoir_distribution['p05']:.4f}  "
        f"медиана {reservoir_distribution['median']:.4f}  "
        f"p95 {reservoir_distribution['p95']:.4f}  "
        f"max {reservoir_distribution['max']:.4f}"
    )
    lines.append(
        f"относительное отличие от поверхностного: "
        f"min {difference['min'] * 100.0:.4f}%  "
        f"медиана {difference['median'] * 100.0:.4f}%  "
        f"max {difference['max'] * 100.0:.4f}%"
    )
    return "\n".join(lines)


def _field_pressure_from_run(output_dir: Path) -> tuple[float, ...]:
    smspec = next(
        (path for path in sorted(output_dir.iterdir()) if path.suffix.upper() == ".SMSPEC"),
        None,
    )
    unsmry = next(
        (path for path in sorted(output_dir.iterdir()) if path.suffix.upper() == ".UNSMRY"),
        None,
    )
    if smspec is None or unsmry is None:
        raise CompensationRangeError(
            f"в каталоге прогона {output_dir} нет пары SMSPEC/UNSMRY: серию "
            "пластового давления FPR прочитать не из чего"
        )
    return _read_field_series(smspec, unsmry).field_pressure_bar


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Измеряет распределение компенсации C(k) по настоящему базовому "
            "прогону и сохраняет артефакт data/compensation-base.json"
        )
    )
    parser.add_argument("--response", type=Path, default=DEFAULT_RESPONSE)
    parser.add_argument("--out", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--run-output", type=Path, default=None)
    parser.add_argument("--pvtnum", type=int, default=DEFAULT_PVTNUM)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    pressures: tuple[float, ...] | None = None
    if args.run_output is not None:
        pressures = _field_pressure_from_run(args.run_output)
    payload = build_artifact(
        args.response,
        args.model_dir,
        pressures,
        pvtnum=args.pvtnum,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(format_report(payload))
    print(f"\nартефакт: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
