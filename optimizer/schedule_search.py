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

## Лимит закачки

На каждом шаге R1 получает пересечение физического потолка базового дека,
явного годового лимита кейса и доступной воды. Последняя задаётся в
`Constraints.infrastructure`: долей реинжекции добытой воды, лагом и
разрешённым внешним источником. Поэтому оптимизатор не может получить ЧДД
из воды, которой нет в постановке.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from config.schema import default_policies
from connectivity.groups import GroupingParams, group_hash, lambda_hash
from contracts import (
    N_INTERVALS,
    Constraints,
    ControlEvent,
    EventKind,
    Groups,
    Lambda,
    NormativeSet,
    OperatingStatus,
    Policies,
    ResponseArtifact,
    Role,
    Schedule,
    Theta,
    canonical_bytes,
    hash_schedule,
    water_supply_policy,
)
from economics import analyze_base_case, load_normatives, load_response_artifact
from policy.fixed_point import Evaluation
from policy.flags import DEFAULT_RULE_FLAGS, RuleFlags
from policy.hierarchy import observations_by_group, run_step
from policy.memory import PolicyMemory, esp_size_for
from policy.rules import r3
from policy.state import PolicyState, RuleContext, WellObservation
from policy.trace import RunTrace
from schedule import (
    BLOCKING_DYNAMIC_VIOLATION_KINDS,
    Violation,
    ViolationKind,
    build_schedule,
    check_dynamic_constraints,
    parse_schedule,
    validate_static,
)
from schedule.canonical import canonicalize
from surrogate.adapter import ResponseAdapter
from surrogate.ensemble import TrajectoryEnsemble
from surrogate.features import ScheduleFeatureizer
from surrogate.model import TrajectorySurrogate, _features
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.npv_block_head import BlockKernelNpvHead, load_direct_npv_head
from surrogate.npv_calibration import NpvCalibration
from surrogate.npv_head import ScenarioNpvHead, scenario_feature_vector
from surrogate.ood import OodScore
from surrogate.scenario_ood import ScenarioDensityDomain
from surrogate.physics_checks import (
    Invariant,
    PhysicsReport,
    Severity,
    check_physics,
    check_prediction,
    severity_of,
)

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


def _validate_npv_head_compatibility(
    npv_head: object, model: object, feature_context_path: Path | str
) -> None:
    context_hash = getattr(npv_head, "feature_context_sha256", "")
    if context_hash:
        actual = hashlib.sha256(Path(feature_context_path).read_bytes()).hexdigest()
        if context_hash != actual:
            raise ScheduleSearchError("NPV head обучен на другом feature context")
    elif getattr(npv_head, "dataset_hash", None) != getattr(
        model, "dataset_hash", None
    ):
        raise ScheduleSearchError(
            "NPV head и trajectory model обучены на разных данных"
        )
    if getattr(npv_head, "wells", None) != getattr(model, "wells", None):
        raise ScheduleSearchError(
            "NPV head и trajectory model имеют разный фонд скважин"
        )
    if getattr(npv_head, "static_feature_names", None) != getattr(
        model, "static_feature_names", None
    ):
        raise ScheduleSearchError("NPV head и trajectory model имеют разную статику")
    physical_weight = float(getattr(npv_head, "physical_npv_weight", 0.0))
    if physical_weight > 0.0 and getattr(
        npv_head, "physical_ensemble_version", ""
    ) != getattr(model, "version", None):
        raise ScheduleSearchError(
            "NPV blend заморожен под другую trajectory ensemble"
        )


class OutOfDomainScheduleError(ScheduleSearchError):
    """A candidate left the training trust region and must not be optimized."""

    def __init__(self, score: float, description: str) -> None:
        self.score = float(score)
        self.description = description
        super().__init__(
            f"кандидат вне области обучения: ood_score={score:.6g}; {description}"
        )


class PhysicallyImpossibleScheduleError(ScheduleSearchError):
    """Прогноз кандидата нарушает физический инвариант — S-04.

    Отдельный тип, а не общая ошибка поиска: причина отказа обязана дойти до
    трассы выбора неизменной. Нарушение физики — не штраф в ЧДД, который
    оптимизатор мог бы «окупить» другими статьями, а запрет: кандидат не
    оценивается и в OPM-пакет не попадает.
    """

    def __init__(self, counts: Mapping[str, int], description: str) -> None:
        self.counts = dict(counts)
        self.description = description
        super().__init__(f"кандидат физически невозможен: {description}")


def _enforce_physics(
    report: PhysicsReport,
    enabled: bool,
    baseline: Mapping[str, int] | None = None,
) -> None:
    """Block every impossible prediction, including violations shared with an anchor.

    ``baseline`` is retained for callers of the old API, but counts never
    excuse a violation on a different well/step. Fixed commissioning is now
    interpreted consistently by features and response timelines.
    """

    if not enabled or report.blocking_count == 0:
        return
    blocking = {
        name: count
        for name, count in sorted(report.counts.items())
        if severity_of(name) is Severity.BLOCKING
    }
    if not blocking:
        return
    description = ", ".join(f"{name}×{count}" for name, count in blocking.items())
    example = next(
        (flag for flag in report.examples if flag.severity is Severity.BLOCKING), None
    )
    if example is not None:
        description += (
            f"; например скважина {example.well}, шаг {example.control_step}: "
            f"{example.detail}"
        )
    raise PhysicallyImpossibleScheduleError(blocking, description)


def _enforce_scenario_ood(
    model_input, model, domain: ScenarioDensityDomain | None
) -> None:
    """Совместная плотность расписания — S-06.

    Покомпонентный `OodScore` спрашивает про каждый признак по отдельности и
    поэтому пропускает совместный сдвиг: на восьми кандидатах контура он даёт
    ровно 0.0000, тогда как относительная ошибка ЧДД на них — 431% по медиане.
    Сценарная плотность на тех же восьми даёт 87…146 при пороге 11.42, то есть
    отвергает все с запасом от 7.6 до 12.8 раз. Проверки дополняют друг друга,
    а не заменяют: первая ловит выход одного признака, вторая — режим целиком.
    """

    if domain is None:
        return
    x, well_index = _features(model_input, model.wells, scenario_context=False)
    vector = scenario_feature_vector(
        x, well_index, n_wells=len(model.wells), feature_set="economic"
    )
    score = domain.score(vector[: domain.feature_width])
    if score <= domain.threshold:
        return
    raise OutOfDomainScheduleError(
        score,
        f"совместная плотность расписания {score:.4g} выше порога "
        f"{domain.threshold:.4g} (квантиль {domain.threshold_quantile} по валидации)",
    )


def _enforce_ood_threshold(ood: OodScore, threshold: float | None) -> None:
    """Reject an extrapolating candidate before adapting or valuing its output."""

    if threshold is None or ood.inside(threshold):
        return
    worst = ood.worst
    description = (
        "неизвестное превышение"
        if worst is None
        else (
            f"{worst.feature}, скважина {worst.well}, "
            f"шаг {worst.control_step}, значение {worst.value:.6g}, "
            f"train [{worst.low:.6g}, {worst.high:.6g}]"
        )
    )
    raise OutOfDomainScheduleError(ood.score, description)


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
    model: TrajectorySurrogate | TrajectoryEnsemble
    control_dates: tuple[date, ...]
    deck_dates: tuple[date, ...]
    t0_deck_date_index: int
    groups: Groups
    lambda_: Lambda
    constraints: Constraints
    flags: RuleFlags
    npv_calibration: NpvCalibration | None = None
    npv_head: ScenarioNpvHead | BlockKernelNpvHead | None = None
    ood_threshold: float | None = None
    # S-06: совместная плотность расписаний. Покомпонентный min/max выдаёт
    # 0.0000 на кандидатах, где ошибка ЧДД достигает 431% — он проверяет
    # каждый признак по отдельности и не видит, что расписание целиком
    # относится к режиму, которого модель не встречала.
    scenario_ood: ScenarioDensityDomain | None = None
    # S-04: кандидат с блокирующим нарушением физики не оценивается. По
    # умолчанию включено — выключать имеет смысл только на замерах, где нужно
    # увидеть, сколько таких кандидатов поиск вообще порождает.
    physics_gate: bool = True


def load_environment(
    *,
    model_dir: Path,
    normatives_path: Path,
    response_path: Path,
    checkpoint_path: Path,
    feature_context_path: Path,
    oil_density_t_per_m3: float = 0.9131,
    lambda_path: Path | None = None,
    npv_calibration_path: Path | None = None,
    npv_head_path: Path | None = None,
    ood_threshold: float | None = None,
    scenario_ood_path: Path | None = None,
    constraints: Constraints | None = None,
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

    case_constraints = Constraints() if constraints is None else constraints
    water_supply_policy(case_constraints)
    raw = (Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    base_schedule = build_schedule(parsed, raw, provenance="policy-search-base")
    real_history = load_response_artifact(response_path)
    normatives = load_normatives(normatives_path)
    policies = default_policies()
    feature_context = ModelZFeatureArtifact.load(feature_context_path)
    model = (
        TrajectoryEnsemble.load(checkpoint_path)
        if Path(checkpoint_path).suffix == ".json"
        else TrajectorySurrogate.load(checkpoint_path)
    )
    scenario_ood = ScenarioDensityDomain.load(scenario_ood_path) if scenario_ood_path is not None else None
    if scenario_ood is not None and scenario_ood.dataset_hash != model.dataset_hash:
        raise ScheduleSearchError("scenario OOD dataset differs from trajectory checkpoint")
    calibration_path = npv_calibration_path
    if calibration_path is None:
        adjacent = Path(checkpoint_path).parent / "npv_calibration.json"
        calibration_path = adjacent if adjacent.exists() else None
    calibration = (
        NpvCalibration.load(calibration_path, model_version=model.version)
        if calibration_path is not None
        else None
    )
    head_path = npv_head_path
    if head_path is None:
        adjacent_head = Path(checkpoint_path).parent / "npv_head.pt"
        head_path = adjacent_head if adjacent_head.exists() else None
    npv_head = load_direct_npv_head(head_path) if head_path is not None else None
    if npv_head is not None:
        _validate_npv_head_compatibility(npv_head, model, feature_context_path)
    if ood_threshold is not None and ood_threshold < 0.0:
        raise ScheduleSearchError("ood_threshold не может быть отрицательным")
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
        constraints=case_constraints,
        flags=flags,
        npv_calibration=calibration,
        npv_head=npv_head,
        ood_threshold=ood_threshold,
        scenario_ood=scenario_ood,
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


def _flow_start_steps(
    schedule: Schedule,
    initial_rates: Mapping[str, tuple[float, float, float]] | None = None,
) -> dict[str, int]:
    """Первый шаг, когда введённая скважина физически может работать.

    `WCON*` задаёт роль и формально вводит скважину, но без `COMPDAT` потока
    ещё нет. В исходном деке это существенно для скважины 71: `WCONPROD`
    стоит на шаге 0, первое заканчивание — на шаге 60. До этого момента
    управляемый слой обязан удерживать её закрытой.
    """

    commissioned = _commission_steps(schedule)
    first_completion: dict[str, int] = {}
    for event in schedule.fixed_deck_events:
        if event.operator != "COMPDAT":
            continue
        first_completion[event.well] = min(
            event.control_step,
            first_completion.get(event.well, event.control_step),
        )
    result: dict[str, int] = {}
    for well, step in commissioned.items():
        initial = schedule.initial_state.get(well)
        initial_rate = (initial_rates or {}).get(well, (0.0, 0.0, 0.0))
        contradictory_open = (
            initial is not None
            and initial.role is not Role.NONE
            and initial.operating_status is OperatingStatus.OPEN
            and initial.setpoint > 0.0
            and max(initial_rate[0], initial_rate[2]) <= 0.0
            and well in first_completion
        )
        if (
            initial is not None
            and initial.role is not Role.NONE
            and not contradictory_open
        ):
            result[well] = 0
            continue
        result[well] = max(step, first_completion.get(well, step))
    return result


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
            w.injection_rate_m3_per_day
            for w in wells
            if w.role is Role.INJ and w.is_open
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
        value = event.value if event.value is not None else 0.0
        current_setpoint[event.well] = value
        current_is_open[event.well] = value > 0.0
    elif event.kind is EventKind.CONVERT_INJ:
        current_role[event.well] = Role.INJ
        current_is_open[event.well] = True
        memory = memory.updated(
            event.well, memory.of(event.well).converted_at(event.control_step)
        )
    return memory


def _advance_memory(
    state: PolicyState, context: RuleContext, *, esp_catalog
) -> PolicyMemory:
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


def _produced_water_rate_m3_per_day(
    state: PolicyState, oil_density_t_per_m3: float
) -> float:
    """Доступная подтоварная вода по текущему отклику поля."""

    if oil_density_t_per_m3 <= 0.0:
        raise ScheduleSearchError("плотность нефти должна быть положительной")
    total = 0.0
    for observation in state.wells.values():
        if observation.role is not Role.PROD or not observation.is_open:
            continue
        oil_volume = observation.oil_rate_t_per_day / oil_density_t_per_m3
        total += max(0.0, observation.liquid_rate_m3_per_day - oil_volume)
    return total


def _interval_produced_water_rate_m3_per_day(
    response: ResponseArtifact,
    control_step: int,
    control_dates: Sequence[date],
    oil_density_t_per_m3: float,
) -> float:
    """Средний дебит добытой воды из объёмов именно этого интервала."""

    days = (control_dates[control_step + 1] - control_dates[control_step]).days
    if days <= 0:
        raise ScheduleSearchError(
            f"control_step={control_step}: неположительная длина интервала"
        )
    water_volume = 0.0
    for item in response.interval_response:
        if item.control_step != control_step:
            continue
        oil_volume = max(0.0, item.oil_mass_delta) / oil_density_t_per_m3
        water_volume += max(0.0, item.liquid_volume_delta - oil_volume)
    return water_volume / days


def _field_limit_for_step(
    *,
    physical_limit_m3_per_day: float,
    constraints: Constraints,
    year: int,
    control_step: int,
    produced_water_by_step: Sequence[float],
) -> float:
    """Пересечение физического, кейсового и водного потолков поля."""

    limits = [physical_limit_m3_per_day]
    explicit = constraints.injection_limits.get(year)
    if explicit is not None:
        limits.append(float(explicit))

    water = water_supply_policy(constraints)
    if water.enabled:
        source_step = control_step - water.lag_steps
        produced = (
            produced_water_by_step[source_step]
            if 0 <= source_step < len(produced_water_by_step)
            else 0.0
        )
        water_limit = water.limit(produced)
        assert water_limit is not None
        limits.append(water_limit)
    return max(0.0, min(limits))


def _active_outage_wells(
    constraints: Constraints, control_step: int
) -> frozenset[str]:
    return frozenset(
        outage.well
        for outage in constraints.well_outages
        if outage.control_step_from <= control_step <= outage.control_step_to
    )


def _outage_events(
    state: PolicyState, wells: frozenset[str]
) -> tuple[ControlEvent, ...]:
    events: list[ControlEvent] = []
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None:
            continue
        target_kind = (
            EventKind.SET_RATE
            if observation.role is Role.INJ
            else EventKind.SET_LRAT
        )
        events.append(
            ControlEvent(
                control_step=state.control_step,
                well=well,
                kind=target_kind,
                value=0.0,
            )
        )
        events.append(
            ControlEvent(
                control_step=state.control_step,
                well=well,
                kind=EventKind.SHUT,
            )
        )
    return tuple(events)


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


def _baseline_conversion_steps(schedule: Schedule) -> dict[str, int]:
    """Шаг перевода под закачку в базовом расписании, по скважинам."""

    steps: dict[str, int] = {}
    for event in schedule.control_events:
        if event.kind is EventKind.CONVERT_INJ:
            previous = steps.get(event.well)
            if previous is None or event.control_step < previous:
                steps[event.well] = event.control_step
    return steps


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
                value=min(
                    current_setpoint.get(well, 0.0), caps.get(well, float("inf"))
                ),
            )
        status_kind = (
            EventKind.OPEN if current_is_open.get(well, False) else EventKind.SHUT
        )
        other = EventKind.SHUT if status_kind is EventKind.OPEN else EventKind.OPEN
        pending.pop((step, well, other), None)
        if (step, well, status_kind) not in pending:
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


def _scale_step_injection_to_limit(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    limit_m3_per_day: float,
    *,
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
) -> float:
    """Последний предохранитель: плотный слой не может превысить фонд воды."""

    keys = [
        key
        for key in pending
        if key[0] == step and key[2] is EventKind.SET_RATE
    ]
    total = sum(float(pending[key].value or 0.0) for key in keys)
    if total <= limit_m3_per_day + 1.0e-9:
        return total
    factor = 0.0 if total <= 0.0 else limit_m3_per_day / total
    for key in keys:
        event = pending[key]
        value = float(event.value or 0.0) * factor
        pending[key] = replace(event, value=value)
        well = event.well
        current_setpoint[well] = value
        if value <= 0.0:
            current_is_open[well] = False
            pending.pop((step, well, EventKind.OPEN), None)
            pending[(step, well, EventKind.SHUT)] = ControlEvent(
                control_step=step,
                well=well,
                kind=EventKind.SHUT,
            )
    return sum(float(pending[key].value or 0.0) for key in keys)


def make_policy(
    env: SearchEnvironment,
    theta: Theta,
    trace_sink: dict,
    *,
    water_reference_response: ResponseArtifact | None = None,
):
    """Возвращает `Policy` (`object -> Schedule`) для одной θ.

    `resolve()` (`policy/fixed_point.py`) не возвращает ничего, кроме
    `Schedule`, из вызова `Policy` — `trace_sink` выносит последнюю собранную
    `RunTrace` наружу через замыкание, чтобы её можно было прочитать после.
    """

    wells = env.base_schedule.meta.wells
    commission_step = _commission_steps(env.base_schedule)
    flow_start_step = _flow_start_steps(
        env.base_schedule,
        _rates_at(env.real_history, _HISTORY_DECK_OFFSET),
    )
    role_at_commission = _role_at_commission(env.base_schedule)
    well_caps, field_limit = _physical_caps(env.base_schedule)
    baseline_injection = _baseline_injection_by_step(env.base_schedule)
    baseline_conversion = _baseline_conversion_steps(env.base_schedule)
    # Уставка, с которой дек вводит скважину: с неё начинается наша, иначе
    # только что введённая скважина стоит с нулём и закрытой.
    commissioning_setpoint: dict[str, float] = {}
    for event in env.base_schedule.control_events:
        if (
            event.kind in (EventKind.SET_RATE, EventKind.SET_LRAT)
            and event.value
            and event.control_step == commission_step.get(event.well, -1)
        ):
            commissioning_setpoint.setdefault(event.well, event.value)
    # Водный отклик суррогата вне обучающего домена может колебаться между
    # итерациями. Бюджет воды внутри одного resolve разрешено только ужимать:
    # это консервативная монотонная оболочка, которая не выдаёт обратно воду,
    # уже признанную недоступной предыдущей реакцией пласта.
    water_limit_ceiling = [float("inf")] * N_INTERVALS

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
            constraints=env.constraints,
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
        produced_water_by_step: list[float] = []
        for step in range(N_INTERVALS):
            # Дек вводит скважину в работу — значит на этом шаге она открыта
            # и стоит на своей вводной уставке. Без этого 22 скважины,
            # входящие внутрь горизонта, оставались закрытыми весь горизонт:
            # прогон G7 20.08 дал по ним 1553 нарушения
            # MODE_CONTRADICTS_SCHEDULE — расписание считает их введёнными,
            # отклик держит выключенными.
            for well, entry in flow_start_step.items():
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
            produced_water_by_step.append(
                _interval_produced_water_rate_m3_per_day(
                    water_reference_response or response,
                    step,
                    env.control_dates,
                    env.oil_density_t_per_m3,
                )
            )
            if not state.wells:
                continue
            step_field_limit = _field_limit_for_step(
                physical_limit_m3_per_day=field_limit,
                constraints=env.constraints,
                year=env.control_dates[step].year,
                control_step=step,
                produced_water_by_step=produced_water_by_step,
            )
            step_field_limit = min(
                step_field_limit, water_limit_ceiling[step]
            )
            water_limit_ceiling[step] = step_field_limit
            injection, offtake = _group_injection_offtake(state, env.groups)
            result = run_step(
                state,
                replace(
                    context,
                    group_injection_m3_per_day=injection,
                    group_offtake_m3_per_day=offtake,
                    baseline_injection_m3_per_day=baseline_injection[step],
                    injection_cap_m3_per_day=well_caps,
                    baseline_conversion_step=baseline_conversion,
                ),
                theta,
                env.flags,
                field_limit_m3_per_day=step_field_limit,
            )
            trace_entries.extend(leveled.entry for leveled in result.trace.entries)
            outage_wells = _active_outage_wells(env.constraints, step)
            not_ready_wells = frozenset(
                well
                for well, entry in flow_start_step.items()
                if commission_step.get(well, entry) <= step < entry
            )
            blocked_wells = outage_wells | not_ready_wells
            decisions = tuple(
                event for event in result.decisions if event.well not in blocked_wells
            ) + _outage_events(state, blocked_wells)
            for event in decisions:
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
            _close_producing_side_on_conversion(pending, step, decisions)
            _emit_dense_layer(
                pending,
                step,
                state,
                current_role=current_role,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                caps=well_caps,
            )
            commanded_injection = _scale_step_injection_to_limit(
                pending,
                step,
                step_field_limit,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
            )
            if commanded_injection > step_field_limit + 1.0e-9:
                raise ScheduleSearchError(
                    f"control_step={step}: плотный слой командует закачку "
                    f"{commanded_injection} м³/сут при доступной воде "
                    f"{step_field_limit} м³/сут"
                )
            context = replace(
                context,
                memory=_advance_memory(
                    state, context, esp_catalog=env.normatives.esp_catalog
                ),
            )
        trace_sink["trace"] = RunTrace(entries=tuple(trace_entries), flags=env.flags)
        candidate = replace(
            env.base_schedule,
            control_events=tuple(pending.values()),
            meta=replace(env.base_schedule.meta, provenance="policy-search-candidate"),
        )
        return canonicalize(candidate)

    return policy


def predict_economics(env: SearchEnvironment, model_input, response: ResponseArtifact) -> dict[str, float]:
    """One economic path shared by search and diagnostic component reports."""
    physical = analyze_base_case(
        response, env.deck_dates, env.t0_deck_date_index, env.normatives, env.policies,
    ).npv_methodology
    if env.npv_head is None:
        blended = env.npv_calibration.apply(physical) if env.npv_calibration is not None else physical
        return {"physical": physical, "blended": blended}
    direct = env.npv_head.predict(model_input)
    weight = float(getattr(env.npv_head, "physical_npv_weight", 0.0))
    return {"direct": direct, "physical": physical, "blended": (1.0 - weight) * direct + weight * physical}


def make_evaluator(env: SearchEnvironment):
    featureizer = ScheduleFeatureizer()
    adapter = ResponseAdapter()

    def evaluator(schedule: Schedule) -> Evaluation:
        model_input = replace(
            featureizer.transform(schedule, env.feature_context.context),
            lambda_edges=(),
        )
        scored = env.model.predict(model_input)
        _enforce_ood_threshold(scored.ood, env.ood_threshold)
        _enforce_scenario_ood(model_input, env.model, env.scenario_ood)
        # Физика проверяется до экономики: считать ЧДД по невозможному
        # прогнозу бессмысленно, а держать такого кандидата в истории поиска
        # с числом — опасно, его потом кто-нибудь сравнит с остальными.
        _enforce_physics(
            check_prediction(
                scored.output,
                schedule=schedule,
                oil_density_t_per_m3=env.oil_density_t_per_m3,
            ),
            env.physics_gate,
        )
        states, intervals = adapter.adapt(
            scored.output, schedule, env.real_history, env.control_dates
        )
        identity = {
            "model_version": env.model.version,
            "schedule_hash": hash_schedule(schedule),
        }
        response = ResponseArtifact(
            source_run_id=f"surrogate-search:{env.model.version[:12]}",
            response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
            state_at_date=states,
            interval_response=intervals,
        )
        npv = predict_economics(env, model_input, response)["blended"]
        return Evaluation(npv=npv, state=response)

    return evaluator


@dataclass(frozen=True, slots=True)
class OpmAdmission:
    """Решение о допуске одного кандидата в OPM-пакет и его обоснование."""

    schedule_hash: str
    admitted: bool
    reason: str
    report: PhysicsReport

    def as_dict(self) -> dict[str, object]:
        return {
            "schedule_hash": self.schedule_hash,
            "admitted": self.admitted,
            "reason": self.reason,
            "physics": self.report.as_dict(),
        }


def admit_to_opm(
    env: SearchEnvironment,
    candidates: Sequence[Schedule],
    *,
    incumbent: Schedule | None = None,
) -> tuple[OpmAdmission, ...]:
    """Отбор кандидатов в пакет OPM по всем семи инвариантам — S-04.

    В отличие от гейта внутри поиска, здесь требуется ``admissible``: все семь
    инвариантов посчитаны и ни один блокирующий не нарушен. Полнота входит в
    условие намеренно — пропущенная проверка не должна быть дешевле
    пройденной, а прогон OPM стоит пятнадцать минут машинного времени.

    ``incumbent`` — проверенное OPM расписание, относительно которого считаются
    differential-инварианты; по умолчанию берётся опора окружения. Они
    определены только на паре, где менялась одна закачка (§7.1 разводит
    семейства возмущений «уровни отбора» и «уровни закачки» именно поэтому);
    на прочих парах кандидат в пакет не попадает, и причина записана словами,
    а не превращается в молчаливый отказ.
    """

    featureizer = ScheduleFeatureizer()
    reference_schedule = env.base_schedule if incumbent is None else incumbent

    def predict(schedule: Schedule):
        return env.model.predict(
            replace(
                featureizer.transform(schedule, env.feature_context.context),
                lambda_edges=(),
            )
        ).output

    reference = predict(reference_schedule)
    decisions: list[OpmAdmission] = []
    for schedule in candidates:
        report = check_physics(
            predict(schedule),
            schedule=schedule,
            reference=reference,
            reference_schedule=reference_schedule,
            lam=env.lambda_,
            oil_density_t_per_m3=env.oil_density_t_per_m3,
        )
        decisions.append(
            OpmAdmission(
                schedule_hash=hash_schedule(schedule),
                admitted=report.admissible,
                reason=admission_reason(report),
                report=report,
            )
        )
    return tuple(decisions)


def admission_reason(report: PhysicsReport) -> str:
    """Словесная причина допуска или отказа — то, что уходит в журнал.

    Отдельная чистая функция: причина обязана быть проверяемой без модели и
    без окружения, иначе её никто не протестирует, а именно она попадёт в
    трассу и в объяснение решения человеку.
    """

    if report.admissible:
        return "все семь инвариантов посчитаны, блокирующих нарушений нет"
    if report.blocking_count:
        blocking = ", ".join(
            f"{name}×{count}"
            for name, count in sorted(report.counts.items())
            if severity_of(name) is Severity.BLOCKING
        )
        return f"блокирующие нарушения: {blocking}"
    return "проверка неполна: " + "; ".join(
        f"{name} — {why}" for name, why in sorted(report.skipped.items())
    )


def candidate_constraint_violations(
    env: SearchEnvironment,
    schedule: Schedule,
    response: ResponseArtifact,
    *,
    trust_surrogate_water_balance: bool = True,
) -> tuple[Violation, ...]:
    """Гейт кейса; водный факт можно отложить до настоящего OPM.

    Старый trajectory surrogate не обучался на ограниченной воде и способен
    предсказывать закачку выше самой команды `SET_RATE`. Поэтому production-
    поиск проверяет водный бюджет по командам (жёсткий assert в `make_policy`),
    а фактический баланс — только submission-трактом на отклике OPM. Остальные
    динамические ограничения кейса продолжают проверяться по отклику.
    """

    static = validate_static(schedule, env.constraints)
    dynamic = check_dynamic_constraints(
        schedule,
        response.state_at_date,
        response.interval_response,
        env.constraints,
        env.oil_density_t_per_m3,
        env.groups,
    )
    dynamic = tuple(
        item
        for item in dynamic
        if item.kind in BLOCKING_DYNAMIC_VIOLATION_KINDS
    )
    if not trust_surrogate_water_balance:
        dynamic = tuple(
            item
            for item in dynamic
            if item.kind is not ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED
        )
    return static.violations + dynamic
