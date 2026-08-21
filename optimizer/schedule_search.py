"""Первый собственный `Schedule*` — задача G5, docs/v2/tasks/integration.md.

Склеивает то, что уже написано и протестировано раздельно: суррогат
(`surrogate/`), правила и агентскую иерархию (`policy/`), неподвижную точку
(`policy/fixed_point.py`), границу оптимизатора (`optimizer/interface.py`) и
сам поиск (`optimizer/search.py`). Ни одна из этих частей не связывала
остальные в один сквозной прогон θ → Schedule* — этот файл и есть та связка.

## Откуда берётся наблюдение по скважине на каждом шаге

`PolicyState`/`WellObservation` за шаг требует роль, "открыта ли" скважина,
физический дебит/приёмистость и текущую уставку.

- **Физические дебиты** (`liquid_rate`, `oil_rate`, `injection_rate`) — из
  `StateAtDate` предсказания суррогата на `deck_date_index = 146 + step`
  (README.md §5: это дата начала интервала управления `step`).
- **Роль, "открыта", уставка** — не из отклика, а из **собственного**
  состояния расписания, которое строит этот же цикл: они полностью
  определяются накопленными до сих пор решениями (`ControlEvent`). Отклик
  сообщает только физику, а не то, что было скомандовано — альтернативы для
  ещё не существующего расписания просто нет.

## Память между шагами

`policy/rules/r3.py` — единственное правило с готовой `advance()` (месяцы
убытка/прибыли для гистерезиса R3). `R1`, `R2`, `R5` памяти не читают.
`R6` (перевод под закачку) читает `memory.converted_to_injection` — эту
запись пишет сам факт применения решения `CONVERT_INJ`, здесь же.
`R4` (порог ЭЦН) читает `memory.esp_nominal_m3_per_day`, но модуля `advance`
для него нет: типоразмер обязан не убывать (`WellMemory.with_esp` — храповик,
`08_contracts.md` §5.1), поэтому корректное обновление после шага —
`max(текущий, размер_под_фактически_достигнутый_дебит)`. Это прямое
следствие храповика, а не отдельное предположение.

## Bootstrap неподвижной точки

Первый вызов `policy` внутри `policy.fixed_point.resolve` получает
`initial_state` — настоящий отклик базового прогона
(`aios/data/base_case/response.json`, задача G1), не синтетику: он
физически существует и уже прошёл приёмку. Последующие вызовы получают
предсказание суррогата на предыдущей `Schedule*`-кандидатуре — ровно то, что
и задумано неподвижной точкой.

## Groups/Lambda — та же честная заглушка, что и в G3

Настоящая λ требует серии экспериментов с отклонениями закачки, которой нет
(`ui/base_artifact.py::_trivial_connectivity`). Здесь используется та же
заглушка: одна группа на весь фонд, нулевая матрица влияния правильной
формы. Из-за этого R1/R5 не видят межскважинного переноса ценности — весь
фонд для них одна группа без внутренней конкуренции за лимит. Это
ограничение заглушки, а не этого файла — унаследовано открыто, не спрятано.

## Лимит закачки при пустом `Constraints`

`Constraints()` пустой означает «нет ограничений сверх физических»
(докстринг `contracts/constraints.py`), но `field_limit_from_constraints`
требует явного числа на год. Вместо нужен явно не связывающий лимит
(`_UNCONSTRAINED_FIELD_LIMIT_M3_PER_DAY`, на порядки больше физической
мощности месторождения) — чтобы R1 распределял закачку по предельной
ценности, а не упирался в искусственный потолок.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from config.schema import default_policies
from contracts import (
    Constraints,
    ControlEvent,
    EventKind,
    Groups,
    Lambda,
    N_INTERVALS,
    NormativeSet,
    Policies,
    ResponseArtifact,
    OperatingStatus,
    Role,
    Schedule,
    Theta,
    canonical_bytes,
    hash_schedule,
)
from connectivity.groups import GroupingParams, group_hash, lambda_hash
from economics import analyze_base_case, load_normatives, load_response_artifact
from policy.fixed_point import Evaluation
from policy.flags import DEFAULT_RULE_FLAGS, RuleFlags
from policy.hierarchy import observations_by_group, run_step
from policy.memory import PolicyMemory, esp_size_for
from policy.rules import r3
from policy.state import PolicyState, RuleContext, WellObservation
from policy.trace import RunTrace
from schedule import build_schedule, parse_schedule
from schedule.canonical import canonicalize
from surrogate.adapter import ResponseAdapter
from surrogate.features import ScheduleFeatureizer
from surrogate.model import TrajectorySurrogate
from surrogate.model_z_context import ModelZFeatureArtifact

_UNCONSTRAINED_FIELD_LIMIT_M3_PER_DAY = 1.0e7

#: Во сколько раз плану позволено превысить то, что месторождение делало в
#: базовом расписании. Запас, а не потолок с потолка: инфраструктура ППД
#: рассчитана на исторические объёмы, и просить у неё кратно больше — это
#: не оптимизация, а невыполнимая команда, которую симулятор молча
#: проигнорирует (прогон G7 20.08: 22 скважины остались закрытыми, 1553
#: нарушения MODE_CONTRADICTS_SCHEDULE).
PHYSICAL_HEADROOM = 1.2
_HISTORY_DECK_OFFSET = 146  # README.md §5: deck_date_index шага = 146 + control_step
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"


class ScheduleSearchError(ValueError):
    pass


def _trivial_connectivity(schedule: Schedule) -> tuple[Lambda, Groups]:
    """Та же честная заглушка, что и в задаче G3 (`ui/base_artifact.py`)."""

    wells = schedule.meta.wells
    roles = {well: schedule.initial_state[well].role for well in wells}
    producers = tuple(well for well in wells if roles[well] is Role.PROD)
    injectors = tuple(well for well in wells if roles[well] is Role.INJ)
    influence = Lambda(
        window_start=schedule.meta.t0,
        window_end=schedule.meta.t0,
        producers=producers,
        injectors=injectors,
        matrix=tuple(tuple(0.0 for _ in injectors) for _ in producers),
        lag_months=0,
        amplitude=0.0,
        stability=0.0,
        rank=0,
        condition_number=0.0,
        achievability_ok={well: False for well in injectors},
    )
    groups_by_id = {"ALL": wells}
    params = GroupingParams()
    groups = Groups(
        groups=groups_by_id,
        lambda_hash=lambda_hash(influence),
        group_hash=group_hash(groups_by_id, influence, params),
    )
    return influence, groups


@dataclass(frozen=True, slots=True)
class SearchEnvironment:
    """Всё, что нужно θ → Schedule* и не меняется между вызовами."""

    base_schedule: Schedule
    real_history: ResponseArtifact
    normatives: NormativeSet
    policies: Policies
    oil_density_t_per_m3: float
    feature_context: ModelZFeatureArtifact
    model: TrajectorySurrogate
    control_dates: tuple[date, ...]
    deck_dates: tuple[date, ...]
    t0_deck_date_index: int
    groups: Groups
    lambda_: Lambda
    flags: RuleFlags


def load_environment(
    *,
    model_dir: Path,
    normatives_path: Path,
    response_path: Path,
    checkpoint_path: Path,
    feature_context_path: Path,
    oil_density_t_per_m3: float = 0.9131,
    lambda_path: Path | None = None,
) -> SearchEnvironment:
    """Окружение поиска. `lambda_path` — измеренная λ, если она уже есть.

    Без неё берётся заглушка из докстринга модуля, и это видно по нулевой
    матрице: при λ=0 правило R1 не различает скважины по предельной ценности
    закачки и душит её по всему фонду, а ЧДД кандидата схлопывается. Путь
    сюда передаёт тот, кто прогнал кампанию замера
    (`connectivity/campaign.py`); файл читается `connectivity.measure.
    load_lambda`, и его отсутствие по явно переданному пути — ошибка, а не
    молчаливый откат к заглушке.
    """

    raw = (Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    base_schedule = build_schedule(parsed, raw, provenance="policy-search-base")
    real_history = load_response_artifact(response_path)
    normatives = load_normatives(normatives_path)
    policies = default_policies()
    feature_context = ModelZFeatureArtifact.load(feature_context_path)
    model = TrajectorySurrogate.load(checkpoint_path)
    if lambda_path is None:
        lambda_, groups = _trivial_connectivity(base_schedule)
    else:
        from connectivity.groups import GroupingParams, build_groups
        from connectivity.measure import load_lambda

        lambda_ = load_lambda(lambda_path)
        groups, _ = build_groups(
            lambda_, GroupingParams(), extra_wells=base_schedule.meta.wells
        )
    flags = RuleFlags(enabled=dict(DEFAULT_RULE_FLAGS))
    return SearchEnvironment(
        base_schedule=base_schedule,
        real_history=real_history,
        normatives=normatives,
        policies=policies,
        oil_density_t_per_m3=oil_density_t_per_m3,
        feature_context=feature_context,
        model=model,
        control_dates=tuple(feature_context.context.control_dates),
        deck_dates=tuple(parsed.dates),
        t0_deck_date_index=parsed.t0_deck_date_index,
        groups=groups,
        lambda_=lambda_,
        flags=flags,
    )


def _commission_steps(schedule: Schedule) -> dict[str, int]:
    """Шаг, с которого скважина AVAILABLE — тем же критерием, что
    `surrogate/schedule_roles.py::build_role_timelines` использует для смены
    роли: `WCONPROD`/`WCONINJE` внутри горизонта — это и есть ввод."""

    steps: dict[str, int] = {}
    for well, state in schedule.initial_state.items():
        if state.role is not Role.NONE:
            steps[well] = 0
    for event in schedule.fixed_deck_events:
        if event.operator in ("WCONPROD", "WCONINJE"):
            steps.setdefault(event.well, event.control_step)
    return steps


def _role_at_commission(schedule: Schedule) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for well, state in schedule.initial_state.items():
        if state.role is not Role.NONE:
            roles[well] = state.role
    for event in schedule.fixed_deck_events:
        if event.operator == "WCONPROD":
            roles.setdefault(event.well, Role.PROD)
        elif event.operator == "WCONINJE":
            roles.setdefault(event.well, Role.INJ)
    return roles


def _rates_at(
    response: ResponseArtifact, deck_date_index: int
) -> dict[str, tuple[float, float, float]]:
    return {
        item.well: (item.liquid_rate, item.oil_rate, item.injection_rate)
        for item in response.state_at_date
        if item.deck_date_index == deck_date_index
    }


def _build_policy_state(
    control_step: int,
    response: ResponseArtifact,
    *,
    wells: tuple[str, ...],
    current_role: Mapping[str, Role],
    current_is_open: Mapping[str, bool],
    current_setpoint: Mapping[str, float],
    commission_step: Mapping[str, int],
    oil_density_t_per_m3: float,
) -> PolicyState:
    rates = _rates_at(response, _HISTORY_DECK_OFFSET + control_step)
    observations: dict[str, WellObservation] = {}
    for well in wells:
        if control_step < commission_step.get(well, 0):
            continue
        role = current_role[well]
        if role is Role.NONE:
            continue
        liquid, oil, injection = rates.get(well, (0.0, 0.0, 0.0))
        liquid = max(liquid, 0.0)
        # Реальный отклик у почти остановленных скважин иногда даёт
        # oil_volume чуть больше liquid_rate (тот же класс шума, что и
        # переток из SURROGATE_HANDOFF.md §6, там же клипуется отдельным
        # порогом) — обводнённость уходит за [0, 1]. Клип по физике:
        # нефти не может быть больше жидкости.
        oil = max(0.0, min(oil, liquid * oil_density_t_per_m3 * (1.0 - 1e-9)))
        observations[well] = WellObservation(
            well=well,
            role=role,
            is_open=current_is_open[well],
            liquid_rate_m3_per_day=liquid,
            oil_rate_t_per_day=oil,
            injection_rate_m3_per_day=max(injection, 0.0),
            setpoint_m3_per_day=current_setpoint[well],
        )
    return PolicyState(control_step=control_step, wells=observations)


def _group_injection_offtake(
    state: PolicyState, groups: Groups
) -> tuple[dict[str, float], dict[str, float]]:
    """R5 (коридор компенсации) требует эти два словаря на входе `RuleContext`
    (`docs/context/08_contracts.md`: компенсация — величина участка, не
    скважины). Считается прямой суммой открытых скважин по роли, тем же
    способом, что `group_demand_rub_per_m3` (R1) агрегирует спрос."""

    by_group = observations_by_group(state, groups)
    injection: dict[str, float] = {}
    offtake: dict[str, float] = {}
    for group_id, wells in by_group.items():
        injection[group_id] = sum(
            w.injection_rate_m3_per_day for w in wells if w.role is Role.INJ and w.is_open
        )
        offtake[group_id] = sum(
            w.liquid_rate_m3_per_day for w in wells if w.role is Role.PROD and w.is_open
        )
    return injection, offtake


def _apply_decision(
    event: ControlEvent,
    *,
    current_role: dict[str, Role],
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    memory: PolicyMemory,
) -> PolicyMemory:
    if event.kind is EventKind.OPEN:
        current_is_open[event.well] = True
    elif event.kind is EventKind.SHUT:
        current_is_open[event.well] = False
    elif event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
        current_setpoint[event.well] = event.value if event.value is not None else 0.0
    elif event.kind is EventKind.CONVERT_INJ:
        current_role[event.well] = Role.INJ
        current_is_open[event.well] = True
        memory = memory.updated(
            event.well, memory.of(event.well).converted_at(event.control_step)
        )
    return memory


def _advance_memory(state: PolicyState, context: RuleContext, *, esp_catalog) -> PolicyMemory:
    memory = context.memory
    for well, observation in state.wells.items():
        current = memory.of(well)
        if observation.role is Role.PROD:
            current = r3.advance(state, replace(context, memory=memory), well)
        if observation.liquid_rate_m3_per_day > 0.0:
            needed = esp_size_for(esp_catalog, observation.liquid_rate_m3_per_day)
            if needed.nominal > current.esp_nominal_m3_per_day:
                current = current.with_esp(needed.nominal)
        memory = memory.updated(well, current)
    return memory


def _physical_caps(schedule: Schedule) -> tuple[dict[str, float], float]:
    """Потолок на скважину и на месторождение — из дека, а не из воздуха.

    Потолок скважины — её собственный исторический максимум в базовом
    расписании: скважина, которая никогда не брала больше 30 м³/сут, не
    возьмёт и 584 тысячи, сколько бы ценности ни насчитало правило R1 по
    измеренной λ. Потолок месторождения — базовая суммарная закачка на шаг,
    обе величины с запасом `PHYSICAL_HEADROOM`.

    Почему это понадобилось. `Constraints()` пустой означает «нет
    ограничений сверх физических», и до измерения λ подстановка заведомо не
    связывающего лимита была безобидной: при нулевой λ предельная ценность
    закачки была нулём везде, и R1 всё равно ничего не раздавал. С настоящей
    λ тот же лимит превратился в раздачу десяти миллионов кубов в сутки —
    режим отказа перевернулся с «душит» на «заливает», и OPM ответил тем,
    что оставил скважины закрытыми.
    """

    per_well: dict[str, float] = {}
    by_step_injection: dict[int, float] = {}
    for event in schedule.control_events:
        if event.value is None or event.value <= 0.0:
            continue
        if event.kind not in (EventKind.SET_RATE, EventKind.SET_LRAT):
            continue
        previous = per_well.get(event.well, 0.0)
        per_well[event.well] = max(previous, event.value * PHYSICAL_HEADROOM)
        if event.kind is EventKind.SET_RATE:
            by_step_injection[event.control_step] = (
                by_step_injection.get(event.control_step, 0.0) + event.value
            )
    field_limit = max(by_step_injection.values(), default=0.0) * PHYSICAL_HEADROOM
    if field_limit <= 0.0:
        raise ScheduleSearchError(
            "в базовом расписании нет ни одной положительной уставки закачки: "
            "физический потолок месторождения выводить не из чего"
        )
    return per_well, field_limit


def _baseline_injection_by_step(schedule: Schedule) -> tuple[dict[str, float], ...]:
    """Уставка закачки базового расписания на каждом шаге, плотно.

    Базовое расписание разрежено: событие пишется только там, где величина
    меняется. R1 же спрашивает про конкретный шаг, поэтому значения
    протягиваются вперёд от `initial_state`. Закрытие скважины обнуляет
    уставку до следующего `SET_RATE`: закачки у закрытой нет, и подставлять
    ей прежний уровень значило бы обещать воду, которой не будет.
    """

    current: dict[str, float] = {
        well: (
            float(state.setpoint or 0.0)
            if state.operating_status is OperatingStatus.OPEN
            else 0.0
        )
        for well, state in schedule.initial_state.items()
    }
    by_step: dict[int, list[ControlEvent]] = {}
    for event in schedule.control_events:
        by_step.setdefault(event.control_step, []).append(event)

    dense: list[dict[str, float]] = []
    for step in range(schedule.meta.n_intervals):
        for event in by_step.get(step, ()):
            if event.kind is EventKind.SET_RATE:
                current[event.well] = float(event.value or 0.0)
            elif event.kind is EventKind.SHUT:
                current[event.well] = 0.0
        dense.append(dict(current))
    return tuple(dense)


def _capped(event: ControlEvent, caps: Mapping[str, float]) -> ControlEvent:
    """Уставка, срезанная физическим потолком скважины."""

    if event.kind not in (EventKind.SET_RATE, EventKind.SET_LRAT):
        return event
    if event.value is None:
        return event
    cap = caps.get(event.well)
    if cap is None or event.value <= cap:
        return event
    return replace(event, value=cap)


def _emit_dense_layer(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    state: PolicyState,
    *,
    current_role: dict[str, Role],
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    caps: Mapping[str, float],
) -> None:
    """Дописать шаг до плотного слоя: у каждой скважины статус и уставка.

    Правила решают не про каждую скважину на каждом шаге — они молчат там,
    где менять нечего, и это правильно. Но `OpmDeckEmitter` требует плотный
    слой: «control_step=0, well='1': плотный слой требует уставку и статус».
    Разреженное расписание проходит `validate_static` и не эмитится в дек,
    то есть до симулятора не доходит вовсе — на этом и остановился первый
    прогон G7.

    Плотность достраивается **из состояния, которое ведёт сам цикл**, а не
    переносом событий базового расписания: перенос смешал бы наши решения с
    чужими и на переведённой под закачку скважине оставил бы уставку отбора
    организаторов. Молчание правила означает «оставить как есть» — ровно это
    и записывается: текущий статус и текущая уставка в том виде, который
    даёт роль скважины на этом шаге.
    """

    for well in state.wells:
        role = current_role.get(well, Role.PROD)
        target_kind = EventKind.SET_RATE if role is Role.INJ else EventKind.SET_LRAT
        if (step, well, target_kind) not in pending:
            pending[(step, well, target_kind)] = ControlEvent(
                control_step=step,
                well=well,
                kind=target_kind,
                value=min(current_setpoint.get(well, 0.0), caps.get(well, float("inf"))),
            )
        status_kind = EventKind.OPEN if current_is_open.get(well, False) else EventKind.SHUT
        other = EventKind.SHUT if status_kind is EventKind.OPEN else EventKind.OPEN
        if (step, well, status_kind) not in pending and (step, well, other) not in pending:
            pending[(step, well, status_kind)] = ControlEvent(
                control_step=step, well=well, kind=status_kind, value=None
            )


def _close_producing_side_on_conversion(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    decisions: Sequence[ControlEvent],
) -> None:
    """На шаге перевода уставка добывающей стороны — только ноль.

    Правила совещаются на состоянии *до* решения: R2 назначает скважине
    уровень отбора, а R6 в том же шаге переводит её под закачку. Оба решения
    законны по отдельности, вместе дают `SET_LRAT` ненулевого значения
    скважине, которая на этом же шаге стала нагнетательной, и
    `validate_static` справедливо это отвергает.

    Дек организаторов на своих переводах пишет ровно это: `CONVERT_INJ`,
    `SET_LRAT 0.0` — закрытие добывающей стороны — и `SET_RATE` с целью
    нового нагнетателя (`bridge/dataset_plan.py::materialize` следует тому же
    правилу). Событие не выбрасывается, а обнуляется: выброшенное оставило бы
    скважину с прежней уставкой отбора, то есть добывающей по смыслу.
    """

    converted = {
        event.well for event in decisions if event.kind is EventKind.CONVERT_INJ
    }
    for well in converted:
        key = (step, well, EventKind.SET_LRAT)
        event = pending.get(key)
        if event is not None and event.value:
            pending[key] = replace(event, value=0.0)


def make_policy(env: SearchEnvironment, theta: Theta, trace_sink: dict):
    """Возвращает `Policy` (`object -> Schedule`) для одной θ.

    `resolve()` (`policy/fixed_point.py`) не возвращает ничего, кроме
    `Schedule`, из вызова `Policy` — `trace_sink` выносит последнюю собранную
    `RunTrace` наружу через замыкание, чтобы её можно было прочитать после.
    """

    wells = env.base_schedule.meta.wells
    commission_step = _commission_steps(env.base_schedule)
    role_at_commission = _role_at_commission(env.base_schedule)
    well_caps, field_limit = _physical_caps(env.base_schedule)
    baseline_injection = _baseline_injection_by_step(env.base_schedule)
    # Уставка, с которой дек вводит скважину: с неё начинается наша, иначе
    # только что введённая скважина стоит с нулём и закрытой.
    commissioning_setpoint: dict[str, float] = {}
    for event in env.base_schedule.control_events:
        if event.kind in (EventKind.SET_RATE, EventKind.SET_LRAT) and event.value:
            key = (event.well, event.control_step)
            if event.control_step == commission_step.get(event.well, -1):
                commissioning_setpoint.setdefault(event.well, event.value)

    def policy(response: ResponseArtifact) -> Schedule:
        current_role: dict[str, Role] = dict(role_at_commission)
        current_is_open: dict[str, bool] = {
            well: env.base_schedule.initial_state[well].operating_status.value == "OPEN"
            for well in wells
        }
        current_setpoint: dict[str, float] = {
            well: env.base_schedule.initial_state[well].setpoint for well in wells
        }
        context = RuleContext(
            normatives=env.normatives,
            oil_density_t_per_m3=env.oil_density_t_per_m3,
            constraints=Constraints(),
            influence=env.lambda_,
            groups=env.groups,
            memory=PolicyMemory(),
        )
        # Внутри одного шага несколько правил могут предложить SET_LRAT/SET_RATE
        # для одной и той же скважины (R2 задаёт уровень, R4 его же ограничивает
        # потолком ЭЦН) — это не конфликт данных, а совещание: правило, стоящее
        # позже в IMPLEMENTED_RULES (`policy/flags.py`), имеет приоритет, потому
        # что R4/R6 по смыслу ограничивают то, что предложил R1/R2. Берём
        # последнее решение на (шаг, скважина, вид события); `canonicalize`
        # иначе видит это как несовместимые дубликаты и падает.
        pending: dict[tuple[int, str, EventKind], ControlEvent] = {}
        trace_entries = []
        for step in range(N_INTERVALS):
            # Дек вводит скважину в работу — значит на этом шаге она открыта
            # и стоит на своей вводной уставке. Без этого 22 скважины,
            # входящие внутрь горизонта, оставались закрытыми весь горизонт:
            # прогон G7 20.08 дал по ним 1553 нарушения
            # MODE_CONTRADICTS_SCHEDULE — расписание считает их введёнными,
            # отклик держит выключенными.
            for well, entry in commission_step.items():
                if entry == step and not current_is_open.get(well, False):
                    current_is_open[well] = True
                    if well in commissioning_setpoint:
                        current_setpoint[well] = commissioning_setpoint[well]
            state = _build_policy_state(
                step,
                response,
                wells=wells,
                current_role=current_role,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                commission_step=commission_step,
                oil_density_t_per_m3=env.oil_density_t_per_m3,
            )
            if not state.wells:
                continue
            injection, offtake = _group_injection_offtake(state, env.groups)
            result = run_step(
                state,
                replace(
                    context,
                    group_injection_m3_per_day=injection,
                    group_offtake_m3_per_day=offtake,
                    baseline_injection_m3_per_day=baseline_injection[step],
                ),
                theta,
                env.flags,
                field_limit_m3_per_day=field_limit,
            )
            trace_entries.extend(leveled.entry for leveled in result.trace.entries)
            for event in result.decisions:
                event = _capped(event, well_caps)
                pending[(event.control_step, event.well, event.kind)] = event
                context = replace(
                    context,
                    memory=_apply_decision(
                        event,
                        current_role=current_role,
                        current_is_open=current_is_open,
                        current_setpoint=current_setpoint,
                        memory=context.memory,
                    ),
                )
            _close_producing_side_on_conversion(pending, step, result.decisions)
            _emit_dense_layer(
                pending,
                step,
                state,
                current_role=current_role,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                caps=well_caps,
            )
            context = replace(
                context,
                memory=_advance_memory(state, context, esp_catalog=env.normatives.esp_catalog),
            )
        trace_sink["trace"] = RunTrace(entries=tuple(trace_entries), flags=env.flags)
        candidate = replace(
            env.base_schedule,
            control_events=tuple(pending.values()),
            meta=replace(env.base_schedule.meta, provenance="policy-search-candidate"),
        )
        return canonicalize(candidate)

    return policy


def make_evaluator(env: SearchEnvironment):
    featureizer = ScheduleFeatureizer()
    adapter = ResponseAdapter()

    def evaluator(schedule: Schedule) -> Evaluation:
        model_input = replace(
            featureizer.transform(schedule, env.feature_context.context),
            lambda_edges=(),
        )
        scored = env.model.predict(model_input)
        states, intervals = adapter.adapt(
            scored.output, schedule, env.real_history, env.control_dates
        )
        identity = {"model_version": env.model.version, "schedule_hash": hash_schedule(schedule)}
        response = ResponseArtifact(
            source_run_id=f"surrogate-search:{env.model.version[:12]}",
            response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
            state_at_date=states,
            interval_response=intervals,
        )
        analysis = analyze_base_case(
            response,
            env.deck_dates,
            env.t0_deck_date_index,
            env.normatives,
            env.policies,
        )
        return Evaluation(npv=analysis.npv_methodology, state=response)

    return evaluator
