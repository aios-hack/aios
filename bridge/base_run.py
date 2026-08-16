"""Базовый прогон Model_Z: физические проверки и замер времени. Задача 7, §4.7.

Прогоняет неизменённое расписание организаторов (нулевая перекладка — те же
control_events/fixed_deck_events, что вернул `schedule.parse_schedule`) через
настоящий OPM Flow, без `--enable-dry-run`. Даёт две вещи, которых до этой
задачи не было нигде в проекте:

- `wallclock_seconds` настоящего прогона Model_Z на этой машине;
- физические диагностики §4.7 — не бинарный gate, а числа для человека:
  тренд обводнённости, пластовое давление, невязка материального баланса,
  и физическое подтверждение (по факту из отклика, не только по расписанию)
  30 переводов под закачку и 22 ввода скважин на своих датах.

Пластовое давление и материальный баланс не входят в `SummarySpec` (§4.3
контракта — это фиксированные девять ключей эталонного расчётчика, менять их
нельзя). Здесь они читаются из отдельных полевых SUMMARY-векторов
(`_FIELD_SUMMARY_KEYS`), которые дописываются в уже эмитированный
`summary_file` уже после `OpmDeckEmitter.emit`, не через `SummarySpec`: три
хешируемых кортежа контракта (`export_keys`/`opm_well_keys`/
`opm_connection_keys`) от этого не меняются, `RunResult.deck_hash`/
`summary_hash` остаются теми же (`static_deck_hash` не берёт `summary_file`
байты, `summary_spec_hash` берёт только `SummarySpec`, не файл на диске).

В Model_Z нет ни одного `AQUCT`/`AQUANCON`/`AQUFETP` — `AQUDIMS 2778` в
RUNSPEC резервирует место, но ни один аквифер не объявлен (проверено grep по
всем `.inc`). Поправка на аквифер в проверке баланса поэтому не нужна:
баланс должен сходиться как для замкнутого пласта.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from contracts import (
    ActiveControlMode,
    RunResult,
    RunStatus,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    T0,
)
from schedule import parse_schedule
from schedule.lossless import ParsedSchedule, _records

from .cache import CachingOpmRunner, RunCache
from .opm_deck import EmittedOpmDeck, OpmDeckEmitter
from .response_loader import ResponseLoader, load_density_by_pvtnum
from .response_loader import _read_smspec, _read_unsmry_report_rows
from .runner import OpmRunner

_SCHEDULE_INCLUDE = "Model_Z_sch.inc"
_FIELD_WGNAME = ":+:+:+:+"

# Диагностические ключи — не часть SummarySpec (§4.3), читаются отдельно.
# FAQR/FAQT намеренно не запрашиваются: в Model_Z нет аквифера, Flow
# помечает их "Unhandled summary keyword" (проверено на MINI.DATA 16.08).
_FIELD_SUMMARY_KEYS: tuple[str, ...] = ("FPR", "FOIP", "FWIP", "FOPT", "FWPT", "FWIT")

# Пределы диагностики — не отбраковывающий oracle (§4.7), а сигнал о явном
# браке конверсии/сходимости, который стоит показать человеку.
MATERIAL_BALANCE_RELATIVE_TOLERANCE = 0.01  # 1% шага накопленного объёма
_PRESSURE_BLOWUP_FACTOR = 3.0  # FPR не должно вырасти/упасть в разы от начального


def baseline_schedule(emitter: OpmDeckEmitter, model_dir: Path) -> Schedule:
    """Расписание с нулевой перекладкой — то, что реально прописали организаторы.

    Тот же приём, что в `bridge/tests/test_opm_deck.py::_baseline_schedule` и
    `bridge/tests/test_runner.py::_baseline_schedule`: control_events и
    fixed_deck_events берутся из `parse_schedule` как есть, `initial_state`
    пуст — плотный слой целиком приходит из уже дописанного в дек управления,
    задача 57 (каноничный Schedule из двух слоёв) сюда не нужна.
    """

    parsed = parse_schedule((model_dir / _SCHEDULE_INCLUDE).read_bytes())
    return Schedule(
        meta=ScheduleMeta(wells=emitter.source_wells, provenance="Model_Z baseline"),
        initial_state={},
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


@dataclass(frozen=True, slots=True)
class RoleTransition:
    """Один перевод PROD → INJ, с настоящей датой из дека (не только control_step)."""

    well: str
    event_date: date
    deck_date_index: int


def find_injection_conversions(parsed: ParsedSchedule) -> tuple[RoleTransition, ...]:
    """Все переводы PROD → INJ по всей истории дека, не только после t0.

    Тот же алгоритм, что и `tools/check_deck_facts.py` §6 (первое появление
    в WCONPROD — роль PROD; первое появление в WCONINJE после этого — перевод):
    он даёт 30 переводов на текущей редакции Model_Z, `CONVERT_INJ` в
    `parsed.control_events` — только 10 из них (те, что внутри горизонта
    управления; остальные 20 случились до t0 и живут в неизменяемой части
    дека, которую `OpmDeckEmitter` копирует байт в байт).
    """

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
    """Один ввод скважины внутри горизонта — из `Schedule.fixed_deck_events`."""

    well: str
    deck_date_index: int


def find_well_introductions(
    parsed: ParsedSchedule, t0_deck_date_index: int
) -> tuple[WellIntroduction, ...]:
    """22 ввода скважин внутри горизонта — первое появление в WCONPROD/WCONINJE.

    `parsed.fixed_deck_events` уже несёт их (control_step = deck_date_index −
    t0_deck_date_index), достаточно спроецировать обратно на deck_date_index,
    ось, по которой размечен `StateAtDate`.
    """

    return tuple(
        WellIntroduction(
            well=event.well,
            deck_date_index=t0_deck_date_index + event.control_step,
        )
        for event in parsed.fixed_deck_events
        if event.operator in ("WCONPROD", "WCONINJE")
    )


def _append_field_summary_keys(summary_file: Path, keys: Sequence[str] = _FIELD_SUMMARY_KEYS) -> None:
    """Дописать диагностические полевые векторы в уже эмитированный SUMMARY include.

    Не через `SummarySpec`/`build_summary_plan` (§4.3: девять ключей эталона
    зафиксированы и хешируются) — просто ещё один блок ключевых слов в том же
    include-файле. `RunResult.deck_hash`/`summary_hash` считаются из
    `SummarySpec`/статики дека (`bridge/runner.py::deck_hashes`), не из байтов
    `summary_file`, так что дописывание их не меняет.
    """

    extra = "".join(f"\n{key}\n/\n" for key in keys)
    with summary_file.open("a", encoding="ascii") as handle:
        handle.write(extra)


@dataclass(frozen=True, slots=True)
class FieldSeries:
    """Полевые диагностики по 371 дате дека — не деньгообразующий тип, только §4.7."""

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


@dataclass(frozen=True, slots=True)
class ConversionCheck:
    transition: RoleTransition
    injection_rate_at_date: float
    verified: bool  # физически: injection_rate > 0 на дате перевода в реальном отклике


@dataclass(frozen=True, slots=True)
class IntroductionCheck:
    introduction: WellIntroduction
    mode_before: ActiveControlMode  # состояние на deck_date_index, до вступления в силу
    mode_at: ActiveControlMode
    verified: bool  # физически: NOT_COMMISSIONED до даты, не NOT_COMMISSIONED начиная с неё


@dataclass(frozen=True, slots=True)
class MaterialBalanceDiagnostics:
    """Невязка накопленного объёма шаг-к-шагу: |Δ(в пласте) − (приток − отток)|.

    Без аквифера (в Model_Z его нет, см. докстринг модуля) это ровно
    материальный баланс: изменение объёма в пласте обязано равняться
    закачанному минус добытому на каждом шаге, с точностью до допуска
    решателя. Систематическая невязка — брак конверсии или несходимость,
    не численный шум.

    **Проверено 16.08 на настоящем прогоне: шаг-к-шагу не годится.** `FWIP`
    Model_Z — около 2.58·10¹¹ м³ (пластовая вода целиком, не только
    закачанная), а `REAL` в `UNSMRY` — 4-байтовый float: точность на этом
    масштабе ≈30 000 м³ (`2.58e11 · 2⁻²³`). Помесячный чистый приток воды —
    порядка 1 500–2 500 м³, то есть меньше шума округления одного шага;
    межшаговая невязка на отдельных датах доходила до 1000%, будучи целиком
    артефактом float32, не браком физики. Баланс поэтому берётся агрегатом
    по всему горизонту 0…370 — там реальный накопленный поток (миллионы м³)
    уже на два порядка больше шума одного сравнения.
    """

    oil_relative_error: float  # |ΔFOIP + ΔFOPT| / |ΔFOPT| по всему горизонту
    water_relative_error: float  # |ΔFWIP − (ΔFWIT − ΔFWPT)| / |ΔFWIT − ΔFWPT|


def _relative_error(delta_stock: float, delta_flow: float) -> float:
    denom = abs(delta_flow)
    return 0.0 if denom == 0.0 else abs(delta_stock - delta_flow) / denom


def compute_material_balance(series: FieldSeries) -> MaterialBalanceDiagnostics:
    # Нефть уходит только через добычу: Δ(в пласте) = −Δ(добыто).
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
    """Полевая обводнённость по объёму (surface): FWPT/(FOPT+FWPT), по каждой дате."""

    watercut: tuple[float, ...]
    first_half_mean: float
    second_half_mean: float
    increasing_as_a_rule: bool  # §4.7: правило, не жёсткий oracle


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
    within_bounds: bool  # не улетает: положительное и не более чем в разы от начального


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
    """`deck_date_index` — дата блока WCONINJE в деке; отклик на неё смотрит

    на deck_date_index + 1: report step D отражает состояние ДО того, как
    управление, объявленное под DATES=D, вступило в силу (проверено на
    реальном отклике 16.08: скважина 12 при первом появлении под 01.01.2007,
    deck_date_index=146, — NOT_COMMISSIONED на 146, RATE_TARGET уже на 147).
    """

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
    """Тот же сдвиг на один report step, что и `_check_conversions`."""

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
    """Полный настоящий прогон Model_Z с нулевой перекладкой. Задача 7.

    Не dry-run: физика считается по-настоящему, `wallclock_seconds` — это и
    есть замер, ради которого задача существует (§7 карточки Андрея).
    """

    emitter = OpmDeckEmitter(model_dir)
    schedule = baseline_schedule(emitter, model_dir)
    deck_dir = work_root / "deck"
    if deck_dir.exists():
        # Эмит детерминирован по (model_dir, schedule) — пересборка не
        # меняет результат, а без очистки повторный вызов падает на
        # непустой destination (`OpmDeckEmitter.emit`). Дорогая часть,
        # настоящий прогон Flow, всё равно идёт через `CachingOpmRunner`
        # ниже и от пересборки дека не страдает.
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
