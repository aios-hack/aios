
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from backend.core.contracts import (
    MATERIAL_BALANCE_RELATIVE_TOLERANCE,
    ActiveControlMode,
    N_INTERVALS,
    RunResult,
    RunStatus,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    T0,
)
from backend.domain.schedule import parse_schedule
from backend.contexts.schedule.domain.lossless import ParsedSchedule, _records
from backend.contexts.schedule.domain.validate_dynamic import control_step_pressures

from backend.contexts.simulation.infrastructure.cache import CachingOpmRunner, RunCache
from backend.contexts.reservoir.infrastructure.opm_deck import EmittedOpmDeck, OpmDeckEmitter
from backend.contexts.reservoir.infrastructure.pvt import PvtTables, load_pvt
from backend.contexts.simulation.infrastructure.response_loader import (
    ResponseLoader,
    load_density_by_pvtnum,
)
from backend.contexts.simulation.infrastructure.response_loader import (
    _read_smspec,
    _read_unsmry_report_rows,
)
from backend.contexts.simulation.infrastructure.runner import OpmRunner
from backend.shared.numeric import relative_error

_SCHEDULE_INCLUDE = "Model_Z_sch.inc"
_FIELD_WGNAME = ":+:+:+:+"

_FIELD_SUMMARY_KEYS: tuple[str, ...] = ("FPR", "FOIP", "FWIP", "FOPT", "FWPT", "FWIT")

_PRESSURE_BLOWUP_FACTOR = 3.0


def baseline_schedule(emitter: OpmDeckEmitter, model_dir: Path) -> Schedule:
    parsed = parse_schedule((model_dir / _SCHEDULE_INCLUDE).read_bytes())
    return Schedule(
        meta=ScheduleMeta(wells=emitter.source_wells, provenance="Model_Z baseline"),
        initial_state={},
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


@dataclass(frozen=True, slots=True)
class RoleTransition:
    well: str
    event_date: date
    deck_date_index: int


def find_injection_conversions(parsed: ParsedSchedule) -> tuple[RoleTransition, ...]:
    seen_prod: set[str] = set()
    seen_inj: set[str] = set()
    transitions: list[RoleTransition] = []
    for block in parsed.blocks:
        if block.keyword not in ("WCONPROD", "WCONINJE") or block.deck_date_index is None:
            continue
        for record in _records(block.raw.splitlines(keepends=True), block.keyword):
            well = record[0]
            if block.keyword == "WCONPROD":
                seen_prod.add(well)
            else:
                if well in seen_prod and well not in seen_inj:
                    transitions.append(
                        RoleTransition(
                            well=well,
                            event_date=block.event_date,
                            deck_date_index=block.deck_date_index,
                        )
                    )
                seen_inj.add(well)
    return tuple(transitions)


@dataclass(frozen=True, slots=True)
class WellIntroduction:
    well: str
    deck_date_index: int


def find_well_introductions(
    parsed: ParsedSchedule, t0_deck_date_index: int
) -> tuple[WellIntroduction, ...]:

    return tuple(
        WellIntroduction(
            well=event.well,
            deck_date_index=t0_deck_date_index + event.control_step,
        )
        for event in parsed.fixed_deck_events
        if event.operator in ("WCONPROD", "WCONINJE")
    )


def _append_field_summary_keys(summary_file: Path, keys: Sequence[str] = _FIELD_SUMMARY_KEYS) -> None:
    extra = "".join(f"\n{key}\n/\n" for key in keys)
    with summary_file.open("a", encoding="ascii") as handle:
        handle.write(extra)


@dataclass(frozen=True, slots=True)
class FieldSeries:
    deck_date_index: tuple[int, ...]
    field_pressure_bar: tuple[float, ...]
    oil_in_place_m3: tuple[float, ...]
    water_in_place_m3: tuple[float, ...]
    oil_produced_cum_m3: tuple[float, ...]
    water_produced_cum_m3: tuple[float, ...]
    water_injected_cum_m3: tuple[float, ...]


def _read_field_series(smspec_path: Path, unsmry_path: Path) -> FieldSeries:
    smspec = _read_smspec(smspec_path)
    columns = {
        key: smspec.column[(key, _FIELD_WGNAME, 0)] for key in _FIELD_SUMMARY_KEYS
    }
    rows = _read_unsmry_report_rows(unsmry_path, smspec.n_vectors)
    return FieldSeries(
        deck_date_index=tuple(range(len(rows))),
        field_pressure_bar=tuple(row[columns["FPR"]] for row in rows),
        oil_in_place_m3=tuple(row[columns["FOIP"]] for row in rows),
        water_in_place_m3=tuple(row[columns["FWIP"]] for row in rows),
        oil_produced_cum_m3=tuple(row[columns["FOPT"]] for row in rows),
        water_produced_cum_m3=tuple(row[columns["FWPT"]] for row in rows),
        water_injected_cum_m3=tuple(row[columns["FWIT"]] for row in rows),
    )


def reservoir_factors_for_steps(
    field_pressure_bar: Sequence[float],
    tables: PvtTables,
    n_intervals: int = N_INTERVALS,
    pvtnum: int = 1,
) -> tuple[tuple[float, float], ...]:
    pressures = control_step_pressures(field_pressure_bar, n_intervals)
    return tuple(
        (
            tables.oil_formation_volume_factor(pressure, pvtnum),
            tables.water_formation_volume_factor(pressure, pvtnum),
        )
        for pressure in pressures
    )


def load_reservoir_factors(
    model_dir: Path,
    field_pressure_bar: Sequence[float],
    n_intervals: int = N_INTERVALS,
    pvtnum: int = 1,
) -> tuple[tuple[float, float], ...]:
    return reservoir_factors_for_steps(
        field_pressure_bar, load_pvt(model_dir), n_intervals, pvtnum
    )


@dataclass(frozen=True, slots=True)
class ConversionCheck:
    transition: RoleTransition
    injection_rate_at_date: float
    verified: bool


@dataclass(frozen=True, slots=True)
class IntroductionCheck:
    introduction: WellIntroduction
    mode_before: ActiveControlMode
    mode_at: ActiveControlMode
    verified: bool


@dataclass(frozen=True, slots=True)
class MaterialBalanceDiagnostics:
    oil_relative_error: float
    water_relative_error: float


def _relative_error(delta_stock: float, delta_flow: float) -> float:
    return relative_error(delta_stock, delta_flow)


def compute_material_balance(series: FieldSeries) -> MaterialBalanceDiagnostics:
    d_oil_in_place = series.oil_in_place_m3[-1] - series.oil_in_place_m3[0]
    d_oil_produced = series.oil_produced_cum_m3[-1] - series.oil_produced_cum_m3[0]
    oil_error = _relative_error(d_oil_in_place, -d_oil_produced)

    d_water_in_place = series.water_in_place_m3[-1] - series.water_in_place_m3[0]
    d_water_injected = series.water_injected_cum_m3[-1] - series.water_injected_cum_m3[0]
    d_water_produced = series.water_produced_cum_m3[-1] - series.water_produced_cum_m3[0]
    water_error = _relative_error(d_water_in_place, d_water_injected - d_water_produced)

    return MaterialBalanceDiagnostics(
        oil_relative_error=oil_error,
        water_relative_error=water_error,
    )


@dataclass(frozen=True, slots=True)
class WatercutTrend:
    watercut: tuple[float, ...]
    first_half_mean: float
    second_half_mean: float
    increasing_as_a_rule: bool


def compute_watercut_trend(series: FieldSeries) -> WatercutTrend:
    watercut = tuple(
        0.0 if (oil + water) == 0.0 else water / (oil + water)
        for oil, water in zip(series.oil_produced_cum_m3, series.water_produced_cum_m3)
    )
    midpoint = len(watercut) // 2
    first_half = watercut[:midpoint] or (0.0,)
    second_half = watercut[midpoint:] or (0.0,)
    first_mean = sum(first_half) / len(first_half)
    second_mean = sum(second_half) / len(second_half)
    return WatercutTrend(
        watercut=watercut,
        first_half_mean=first_mean,
        second_half_mean=second_mean,
        increasing_as_a_rule=second_mean >= first_mean,
    )


@dataclass(frozen=True, slots=True)
class PressureDiagnostics:
    field_pressure_bar: tuple[float, ...]
    initial_bar: float
    min_bar: float
    max_bar: float
    within_bounds: bool


def compute_pressure_diagnostics(series: FieldSeries) -> PressureDiagnostics:
    pressures = series.field_pressure_bar
    initial = pressures[0]
    lowest = min(pressures)
    highest = max(pressures)
    within_bounds = (
        lowest > 0.0
        and highest < initial * _PRESSURE_BLOWUP_FACTOR
        and lowest > initial / _PRESSURE_BLOWUP_FACTOR
    )
    return PressureDiagnostics(
        field_pressure_bar=pressures,
        initial_bar=initial,
        min_bar=lowest,
        max_bar=highest,
        within_bounds=within_bounds,
    )


@dataclass(frozen=True, slots=True)
class BaseRunReport:
    run_result: RunResult
    wallclock_seconds: float
    field_series: FieldSeries
    material_balance: MaterialBalanceDiagnostics
    watercut_trend: WatercutTrend
    pressure: PressureDiagnostics
    conversions: tuple[ConversionCheck, ...]
    introductions: tuple[IntroductionCheck, ...]


def _check_conversions(
    transitions: Sequence[RoleTransition],
    state_by_well_date: dict[tuple[str, int], StateAtDate],
) -> tuple[ConversionCheck, ...]:

    checks = []
    for transition in transitions:
        state = state_by_well_date[(transition.well, transition.deck_date_index + 1)]
        checks.append(
            ConversionCheck(
                transition=transition,
                injection_rate_at_date=state.injection_rate,
                verified=state.injection_rate > 0.0,
            )
        )
    return tuple(checks)


def _check_introductions(
    introductions: Sequence[WellIntroduction],
    state_by_well_date: dict[tuple[str, int], StateAtDate],
) -> tuple[IntroductionCheck, ...]:

    checks = []
    for intro in introductions:
        mode_before = state_by_well_date[(intro.well, intro.deck_date_index)].active_control_mode
        mode_at = state_by_well_date[(intro.well, intro.deck_date_index + 1)].active_control_mode
        verified = (
            mode_before is ActiveControlMode.NOT_COMMISSIONED
            and mode_at is not ActiveControlMode.NOT_COMMISSIONED
        )
        checks.append(
            IntroductionCheck(
                introduction=intro,
                mode_before=mode_before,
                mode_at=mode_at,
                verified=verified,
            )
        )
    return tuple(checks)


def run_base_case(
    model_dir: Path,
    work_root: Path,
    *,
    use_cache: bool = True,
) -> BaseRunReport:

    emitter = OpmDeckEmitter(model_dir)
    schedule = baseline_schedule(emitter, model_dir)
    deck_dir = work_root / "deck"
    if deck_dir.exists():
        shutil.rmtree(deck_dir)
    deck: EmittedOpmDeck = emitter.emit(schedule, deck_dir)
    _append_field_summary_keys(deck.summary_file)

    base_runner = OpmRunner(work_root / "runs")
    if use_cache:
        runner = CachingOpmRunner(base_runner, RunCache(work_root / "cache"))
    else:
        runner = base_runner
    result = runner.run(deck, schedule)
    if result.status is not RunStatus.OK:
        raise RuntimeError(f"базовый прогон не OK: {result.status} — {result.message}")

    smspec_path = next(Path(p) for p in result.artifacts if p.upper().endswith("SMSPEC"))
    unsmry_path = next(Path(p) for p in result.artifacts if p.upper().endswith("UNSMRY"))
    field_series = _read_field_series(smspec_path, unsmry_path)

    density_by_pvtnum = load_density_by_pvtnum(model_dir)
    response = ResponseLoader().load(result, deck.summary_plan, schedule, density_by_pvtnum)
    state_by_well_date = {
        (state.well, state.deck_date_index): state for state in response.state_at_date
    }

    parsed = parse_schedule((model_dir / _SCHEDULE_INCLUDE).read_bytes())
    transitions = find_injection_conversions(parsed)
    introductions = find_well_introductions(parsed, parsed.t0_deck_date_index)

    return BaseRunReport(
        run_result=result,
        wallclock_seconds=result.wallclock_seconds,
        field_series=field_series,
        material_balance=compute_material_balance(field_series),
        watercut_trend=compute_watercut_trend(field_series),
        pressure=compute_pressure_diagnostics(field_series),
        conversions=_check_conversions(transitions, state_by_well_date),
        introductions=_check_introductions(introductions, state_by_well_date),
    )
