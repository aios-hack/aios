"""Физические инварианты прогноза суррогата — S-03.

Куратор на чекпоинте 31.08 (00:15:25) спросила ровно две вещи: заложена ли
физика в архитектуру и проверено ли, что она нигде не нарушается. Первое —
свойство модели (параметризация через обводнённость, неотрицательность в
``RawWellStepPrediction``), второе — свойство конкретного прогноза, и его
нельзя доказать ссылкой на первое. Модуль измеряет и то и другое: инвариант,
невозможный по построению в текущем пути кода, всё равно считается, потому
что «невозможно по построению» — утверждение о коде, а не о прогнозе,
который пришёл из файла чекпоинта другой версии.

Семь инвариантов плана (`FINAL_PLAN.md` §6.3) делятся на две группы. Пять
проверяются на одном прогнозе, два — differential: они сравнивают кандидата
с опорой, потому что «отклик на закачку» и «материальный баланс» — это
утверждения о приросте, а прирост существует только относительно чего-то.

Нарушение — не штраф в лоссе, а флаг кандидата: пока флаг не снят, кандидат
не уходит в OPM (S-04). Единственное исключение — пределы BHP: они
предупреждение, потому что предсказанное забойное вне предела означает, что
OPM переведёт скважину на другой режим управления, а не что прогноз
физически невозможен.

Отчёт всегда называет, какие инварианты выполнялись, а какие пропущены и
почему. Ноль флагов при двух пропущенных инвариантах — это не «физика в
порядке», и отчёт не даёт прочитать себя так.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from backend.contexts.simulation.infrastructure.response_loader import _build_well_timelines
from backend.core.contracts import EventKind, Lambda, OperatingStatus, Role, Schedule

from .raw_model_output import RawModelOutput, RawWellStepPrediction
from .schedule_roles import build_role_timelines

FORMAT = "aios.surrogate-physics-report.v1"

# Плотность нефти Model_Z, т/м³ — тот же дефолт, что у `SurrogateSettings`
# (`model.py`). Передаётся параметром, а не берётся отсюда молча: на другом
# месторождении она другая, и тождество нефть = жидкость × (1 − обводнённость)
# считается через неё.
DEFAULT_OIL_DENSITY_T_PER_M3 = 0.9131

# Прогноз — число с плавающей точкой после ансамблевого усреднения и
# калибровки, поэтому «равно нулю» и «неотрицательно» проверяются с допуском.
# Допуск абсолютный и в физических единицах: 1 л на интервал и 1 л/сут —
# заведомо ниже разрешающей способности любого решения, но выше шума float32.
DEFAULT_ZERO_TOLERANCE = 1e-3

# Обводнённость безразмерна, и допуск для неё обязан быть безразмерным тоже.
# Абсолютный допуск в м³ здесь не работает: у скважины со 100 м³ жидкости за
# интервал перевод массы нефти в объём через плотность даёт погрешность
# порядка 0.01 м³, то есть 1e-4 в единицах обводнённости — ниже 1e-3, но выше
# любого разумного допуска в м³.
#
# Порог выбран по измерению, а не назначен: на настоящем отклике OPM
# (`data/constrained-opm-feasible-final`) обводнённость уходит ниже нуля на
# 394 интервалах из 13 820 (2.85%), медиана этих отклонений −6.4e-5, но
# распределение непрерывно тянется до −0.152. Глубже 1e-3 — 119 интервалов,
# глубже 1e-2 — девять. Значит, отрицательная обводнённость в разобранном
# отклике не сводится к арифметике: это перетоки, и 1e-3 отделяет их от
# погрешности перевода единиц, не пряча.
DEFAULT_WATERCUT_TOLERANCE = 1e-3

# Differential-инварианты сравнивают накопленные за горизонт объёмы, где
# абсолютный допуск бессмысленен: закачка нагнетательной за 224 месяца —
# сотни тысяч м³. Относительный допуск в 0.5% от большей из сравниваемых
# величин отделяет физическое нарушение от арифметики суммирования.
DEFAULT_RELATIVE_TOLERANCE = 5e-3

# Сколько примеров каждого вида сохранять в отчёте. Полный счётчик ведётся по
# всем узлам: 103 скважины × 224 шага — 23 072 узла, и сломанный прогноз
# способен дать флаг на каждом. Отчёт должен оставаться читаемым.
DEFAULT_MAX_EXAMPLES_PER_INVARIANT = 8


class PhysicsCheckError(ValueError):
    """Проверку нельзя выполнить: вход противоречив, а не прогноз плох."""


class Invariant(Enum):
    """Семь инвариантов §6.3 плана."""

    NON_NEGATIVE = "NON_NEGATIVE"
    WATERCUT_RANGE = "WATERCUT_RANGE"
    CUMULATIVE_MONOTONIC = "CUMULATIVE_MONOTONIC"
    SHUT_WELL_FLOW = "SHUT_WELL_FLOW"
    BHP_LIMIT = "BHP_LIMIT"
    INJECTION_RESPONSE = "INJECTION_RESPONSE"
    MATERIAL_BALANCE = "MATERIAL_BALANCE"


class Severity(Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


# BHP — предупреждение: предсказанное забойное вне предела дека означает
# смену режима управления в OPM, а не невозможный прогноз. Остальные шесть
# описывают состояния, которых пласт не производит ни при каком режиме.
_SEVERITY: Mapping[Invariant, Severity] = {
    Invariant.NON_NEGATIVE: Severity.BLOCKING,
    Invariant.WATERCUT_RANGE: Severity.BLOCKING,
    Invariant.CUMULATIVE_MONOTONIC: Severity.BLOCKING,
    Invariant.SHUT_WELL_FLOW: Severity.BLOCKING,
    Invariant.BHP_LIMIT: Severity.WARNING,
    Invariant.INJECTION_RESPONSE: Severity.BLOCKING,
    Invariant.MATERIAL_BALANCE: Severity.BLOCKING,
}


def severity_of(invariant: Invariant | str) -> Severity:
    """Строгость инварианта. Публична, чтобы гейты не заводили вторую таблицу."""

    return _SEVERITY[Invariant(invariant) if isinstance(invariant, str) else invariant]


_SINGLE_PREDICTION_INVARIANTS: tuple[Invariant, ...] = (
    Invariant.NON_NEGATIVE,
    Invariant.WATERCUT_RANGE,
    Invariant.CUMULATIVE_MONOTONIC,
    Invariant.SHUT_WELL_FLOW,
    Invariant.BHP_LIMIT,
)
_DIFFERENTIAL_INVARIANTS: tuple[Invariant, ...] = (
    Invariant.INJECTION_RESPONSE,
    Invariant.MATERIAL_BALANCE,
)

_RATE_CHANNELS: tuple[str, ...] = ("liquid_rate", "injection_rate")
_VOLUME_CHANNELS: tuple[str, ...] = (
    "oil_mass_delta",
    "liquid_volume_delta",
    "injection_volume_delta",
)

# Позиция предела BHP в `raw_args` фиксированного события дека. Имя скважины
# в `raw_args` не входит (оно в `FixedDeckEvent.well`), поэтому индексы на
# единицу меньше позиции в записи дека:
#   WCONPROD  статус режим 1* 1* 1* LRAT 1* BHP …  →  raw_args[7]
#   WCONINJE  флюид статус режим RATE 1* BHP …     →  raw_args[5]
_BHP_ARG_INDEX: Mapping[str, int] = {"WCONPROD": 7, "WCONINJE": 5}


@dataclass(frozen=True, slots=True)
class PhysicsFlag:
    """Одно нарушение. ``control_step`` пуст у инвариантов, считаемых за горизонт."""

    invariant: Invariant
    severity: Severity
    well: str
    observed: float
    limit: float
    detail: str
    control_step: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "invariant": self.invariant.value,
            "severity": self.severity.value,
            "well": self.well,
            "control_step": self.control_step,
            "observed": self.observed,
            "limit": self.limit,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class PhysicsReport:
    """Итог проверки. ``counts`` полон, ``examples`` ограничен."""

    counts: Mapping[str, int]
    examples: tuple[PhysicsFlag, ...]
    evaluated: tuple[Invariant, ...]
    skipped: Mapping[str, str]
    n_nodes: int
    n_wells: int
    format: str = FORMAT

    def __post_init__(self) -> None:
        known = {invariant.value for invariant in Invariant}
        unknown = (set(self.counts) | set(self.skipped)) - known
        if unknown:
            raise PhysicsCheckError(f"неизвестные инварианты в отчёте: {sorted(unknown)}")
        overlap = {invariant.value for invariant in self.evaluated} & set(self.skipped)
        if overlap:
            raise PhysicsCheckError(
                f"инвариант одновременно выполнен и пропущен: {sorted(overlap)}"
            )

    @property
    def n_flags(self) -> int:
        return sum(self.counts.values())

    @property
    def blocking_count(self) -> int:
        return sum(
            count
            for name, count in self.counts.items()
            if _SEVERITY[Invariant(name)] is Severity.BLOCKING
        )

    @property
    def warning_count(self) -> int:
        return self.n_flags - self.blocking_count

    @property
    def complete(self) -> bool:
        """Все семь инвариантов действительно посчитаны."""

        return len(self.evaluated) == len(Invariant)

    @property
    def admissible(self) -> bool:
        """Кандидат допускается в OPM-пакет (S-04).

        Требуется и отсутствие блокирующих флагов, и полнота проверки:
        пропущенный инвариант — не пройденный инвариант.
        """

        return self.complete and self.blocking_count == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "n_nodes": self.n_nodes,
            "n_wells": self.n_wells,
            "n_flags": self.n_flags,
            "blocking_count": self.blocking_count,
            "warning_count": self.warning_count,
            "complete": self.complete,
            "admissible": self.admissible,
            "counts": dict(sorted(self.counts.items())),
            "evaluated": sorted(invariant.value for invariant in self.evaluated),
            "skipped": dict(sorted(self.skipped.items())),
            "examples": [flag.as_dict() for flag in self.examples],
        }


@dataclass(frozen=True, slots=True)
class BhpLimits:
    """Пределы забойного давления, прочитанные из дека, а не назначенные.

    Значения приходят из фиксированного слоя расписания — того же, что
    эмитируется обратно в `wells_schedule.inc`. Поэтому перенос на другое
    месторождение не требует правки кода: у Model_Y будут свои пределы из
    его собственного дека.
    """

    producer_floor: Mapping[str, float]
    injector_ceiling: Mapping[str, float]
    producer_default: float | None
    injector_default: float | None

    @classmethod
    def from_schedule(cls, schedule: Schedule) -> "BhpLimits":
        floors: dict[str, float] = {}
        ceilings: dict[str, float] = {}
        for event in schedule.fixed_deck_events:
            index = _BHP_ARG_INDEX.get(event.operator)
            if index is None or index >= len(event.raw_args):
                continue
            value = _deck_float(event.raw_args[index])
            if value is None:
                continue
            target = floors if event.operator == "WCONPROD" else ceilings
            # Дек переоткрывает скважину несколько раз; предел на всех
            # записях один. Если он когда-нибудь разойдётся, разойдётся и
            # дефолт ниже, и это станет видно, а не растворится.
            target[event.well] = value
        return cls(
            producer_floor=floors,
            injector_ceiling=ceilings,
            producer_default=_unique_value(floors.values()),
            injector_default=_unique_value(ceilings.values()),
        )

    def floor_for(self, well: str) -> float | None:
        return self.producer_floor.get(well, self.producer_default)

    def ceiling_for(self, well: str) -> float | None:
        return self.injector_ceiling.get(well, self.injector_default)

    @property
    def usable(self) -> bool:
        return self.producer_default is not None or self.injector_default is not None


def _deck_float(token: str) -> float | None:
    """`1*` дека — «умолчание», а не число."""

    text = token.strip().strip("'\"")
    if not text or text.endswith("*"):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _unique_value(values: Iterable[float]) -> float | None:
    distinct = {round(value, 9) for value in values}
    return next(iter(distinct)) if len(distinct) == 1 else None


class _FlagSink:
    """Считает все нарушения, хранит ограниченное число примеров."""

    def __init__(self, max_examples: int) -> None:
        if max_examples < 1:
            raise PhysicsCheckError("max_examples должен быть положительным")
        self._max_examples = max_examples
        self._counts: Counter[str] = Counter()
        self._examples: list[PhysicsFlag] = []

    def add(
        self,
        invariant: Invariant,
        *,
        well: str,
        observed: float,
        limit: float,
        detail: str,
        control_step: int | None = None,
    ) -> None:
        name = invariant.value
        self._counts[name] += 1
        if self._counts[name] <= self._max_examples:
            self._examples.append(
                PhysicsFlag(
                    invariant=invariant,
                    severity=_SEVERITY[invariant],
                    well=well,
                    observed=observed,
                    limit=limit,
                    detail=detail,
                    control_step=control_step,
                )
            )

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    @property
    def examples(self) -> tuple[PhysicsFlag, ...]:
        return tuple(self._examples)


def check_prediction(
    raw: RawModelOutput,
    *,
    schedule: Schedule,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    bhp_limits: BhpLimits | None = None,
    zero_tolerance: float = DEFAULT_ZERO_TOLERANCE,
    watercut_tolerance: float = DEFAULT_WATERCUT_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    """Пять инвариантов, проверяемых на одном прогнозе.

    ``bhp_limits`` по умолчанию читаются из фиксированного слоя ``schedule``.
    Если дек их не задаёт, инвариант ``BHP_LIMIT`` уходит в ``skipped`` с
    причиной, а не считается пройденным.

    Два differential-инварианта всегда попадают в ``skipped``: на одном
    прогнозе они не определены. Отчёт поэтому никогда не ``complete``, и это
    правильно — «пять из семи» не должно читаться как «физика проверена».
    """

    if oil_density_t_per_m3 <= 0.0:
        raise PhysicsCheckError("oil_density_t_per_m3 должна быть положительной")
    if zero_tolerance < 0.0:
        raise PhysicsCheckError("zero_tolerance не может быть отрицательным")
    if watercut_tolerance < 0.0:
        raise PhysicsCheckError("watercut_tolerance не может быть отрицательным")
    _require_same_axis(raw, schedule)

    limits = bhp_limits if bhp_limits is not None else BhpLimits.from_schedule(schedule)
    role_timelines = build_role_timelines(schedule)
    well_timelines = _build_well_timelines(schedule)
    sink = _FlagSink(max_examples)

    evaluated = list(_SINGLE_PREDICTION_INVARIANTS)
    skipped: dict[str, str] = {
        invariant.value: "инвариант определён только на паре опора/кандидат"
        for invariant in _DIFFERENTIAL_INVARIANTS
    }
    if not limits.usable:
        evaluated.remove(Invariant.BHP_LIMIT)
        skipped[Invariant.BHP_LIMIT.value] = (
            "дек не задаёт пределов BHP ни для одной скважины: "
            "WCONPROD/WCONINJE без числового значения предела"
        )

    for node in raw.nodes:
        role = role_timelines[node.well].role(node.control_step)
        _check_non_negative(node, sink=sink, tolerance=zero_tolerance)
        _check_watercut(
            node,
            sink=sink,
            oil_density_t_per_m3=oil_density_t_per_m3,
            zero_tolerance=zero_tolerance,
            watercut_tolerance=watercut_tolerance,
        )
        _check_cumulative(node, sink=sink, tolerance=zero_tolerance)
        _check_shut_well(
            node,
            sink=sink,
            timeline=well_timelines[node.well],
            tolerance=zero_tolerance,
        )
        if Invariant.BHP_LIMIT in evaluated:
            _check_bhp(node, sink=sink, role=role, limits=limits)

    return PhysicsReport(
        counts=sink.counts,
        examples=sink.examples,
        evaluated=tuple(evaluated),
        skipped=skipped,
        n_nodes=len(raw.nodes),
        n_wells=len(raw.wells),
    )


def injection_only_pair(
    reference_schedule: Schedule, candidate_schedule: Schedule
) -> tuple[bool, str]:
    """Отличается ли кандидат от опоры только уставками закачки.

    Differential-инварианты идентифицируемы лишь на такой паре. Если между
    опорой и кандидатом поменялись ещё и уставки добычи, открытия, остановки
    или переводы, прирост добытой жидкости объясняется не только закачкой, и
    ни знак отклика, ни водный баланс из пары не выводятся. Пакет возмущений
    §7.1 плана разводит семейства «уровни отбора» и «уровни закачки» именно
    поэтому — проверка опирается на это разделение, а не требует его на веру.
    """

    def events(schedule: Schedule) -> dict[tuple[int, str, str], float | None]:
        return {
            (event.control_step, event.well, event.kind.value): getattr(event, "value", None)
            for event in schedule.control_events
        }

    left, right = events(reference_schedule), events(candidate_schedule)
    changed = {key for key in set(left) | set(right) if left.get(key) != right.get(key)}
    if not changed:
        return False, "опора и кандидат несут одинаковые управляющие события"
    other = sorted({key[2] for key in changed} - {EventKind.SET_RATE.value})
    if other:
        return False, f"кандидат меняет не только закачку: {', '.join(other)}"
    return True, ""


def lambda_column_sums(lam: Lambda) -> dict[str, float]:
    """Σ_p λ[p][i] по каждой нагнетательной — диагностика артефакта связности.

    План §6.3 формулирует материальный баланс как CRM-условие
    ``Σ_p f[p][i] ≤ 1``. К измеренной λ оно неприменимо: контракт ``Lambda``
    прямо говорит, что сумма по столбцу инвариантом не является — это
    размерные коэффициенты чувствительности (м³ прироста жидкости на м³
    закачки), а не безразмерные доли аллокации CRM. Функция возвращает суммы,
    чтобы расхождение было измеряемым числом в карточке суррогата, а не
    превращалось в ложные нарушения физики прогноза.
    """

    sums: dict[str, float] = {}
    for column, injector in enumerate(lam.injectors):
        sums[injector] = sum(lam.matrix[row][column] for row in range(len(lam.producers)))
    return sums


def _dominant_neighbourhoods(lam: Lambda) -> dict[str, tuple[str, ...]]:
    """Непересекающееся разбиение добывающих по сильнейшей связи.

    λ плотная: нулевых коэффициентов лишь пятая часть, поэтому «все связанные
    добывающие» для каждой нагнетательной — это почти весь фонд, и сумма их
    прироста жидкости не сопоставима с приростом закачки одной скважины.
    Каждая добывающая относится к той нагнетательной, чей коэффициент для неё
    наибольший; окрестности не пересекаются, и прирост не учитывается дважды.
    """

    neighbourhoods: dict[str, list[str]] = {injector: [] for injector in lam.injectors}
    for row, producer in enumerate(lam.producers):
        weights = lam.matrix[row]
        best = max(range(len(lam.injectors)), key=lambda column: weights[column])
        if weights[best] > 0.0:
            neighbourhoods[lam.injectors[best]].append(producer)
    return {injector: tuple(producers) for injector, producers in neighbourhoods.items()}


def check_pair(
    reference: RawModelOutput,
    candidate: RawModelOutput,
    *,
    reference_schedule: Schedule,
    candidate_schedule: Schedule,
    lam: Lambda,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    """Два differential-инварианта: отклик на закачку и материальный баланс.

    ``INJECTION_RESPONSE`` — по каждой нагнетательной, на её непересекающейся
    окрестности: коэффициенты λ положительны, значит рост закачки не может
    уменьшить суммарную добычу жидкости тех добывающих, для которых эта
    нагнетательная — сильнейшая связь.

    ``MATERIAL_BALANCE`` — на уровне поля и только по воде: прирост добытой
    воды за горизонт не превосходит прироста закачки. Именно вода, а не
    жидкость: прирост нефти берётся из пласта, а не из нагнетательной, и
    сравнивать его с закачкой значит требовать неверного. По отдельной
    нагнетательной баланс не считается — вода мигрирует между окрестностями,
    и такое требование было бы строже физики.
    """

    if oil_density_t_per_m3 <= 0.0:
        raise PhysicsCheckError("oil_density_t_per_m3 должна быть положительной")
    if relative_tolerance < 0.0:
        raise PhysicsCheckError("relative_tolerance не может быть отрицательным")
    if reference.wells != candidate.wells:
        raise PhysicsCheckError("опора и кандидат построены на разных осях скважин")
    if reference.canonical_schedule_hash == candidate.canonical_schedule_hash:
        raise PhysicsCheckError(
            "опора и кандидат — одно расписание: differential-инварианты не определены"
        )

    known = set(reference.wells)
    missing = (set(lam.producers) | set(lam.injectors)) - known
    if missing:
        raise PhysicsCheckError(
            f"λ ссылается на скважины вне прогноза: {sorted(missing)[:5]}"
        )

    identifiable, reason = injection_only_pair(reference_schedule, candidate_schedule)
    if not identifiable:
        return PhysicsReport(
            counts={},
            examples=(),
            evaluated=(),
            skipped={invariant.value: reason for invariant in _DIFFERENTIAL_INVARIANTS},
            n_nodes=len(candidate.nodes),
            n_wells=len(candidate.wells),
        )

    delta_liquid = _horizon_delta(reference, candidate, "liquid_volume_delta")
    delta_oil_mass = _horizon_delta(reference, candidate, "oil_mass_delta")
    delta_injection = _horizon_delta(reference, candidate, "injection_volume_delta")
    sink = _FlagSink(max_examples)

    for injector, producers in _dominant_neighbourhoods(lam).items():
        injected = delta_injection.get(injector, 0.0)
        if not producers or injected <= _scaled_tolerance(injected, relative_tolerance):
            continue
        produced = sum(delta_liquid.get(producer, 0.0) for producer in producers)
        if produced < -_scaled_tolerance(injected, relative_tolerance):
            sink.add(
                Invariant.INJECTION_RESPONSE,
                well=injector,
                observed=produced,
                limit=0.0,
                detail=(
                    f"закачка выросла на {injected:.1f} м³, а суммарная жидкость "
                    f"{len(producers)} добывающих её окрестности упала на {-produced:.1f} м³"
                ),
            )

    injected_total = sum(delta_injection.get(well, 0.0) for well in lam.injectors)
    water_total = sum(
        delta_liquid.get(producer, 0.0)
        - delta_oil_mass.get(producer, 0.0) / oil_density_t_per_m3
        for producer in lam.producers
    )
    tolerance = _scaled_tolerance(max(water_total, injected_total), relative_tolerance)
    if water_total > injected_total + tolerance:
        sink.add(
            Invariant.MATERIAL_BALANCE,
            well="<поле>",
            observed=water_total,
            limit=injected_total,
            detail=(
                f"добыто воды на {water_total:.1f} м³ больше при приросте закачки "
                f"{injected_total:.1f} м³: вода взялась ниоткуда"
            ),
        )

    return PhysicsReport(
        counts=sink.counts,
        examples=sink.examples,
        evaluated=_DIFFERENTIAL_INVARIANTS,
        skipped={},
        n_nodes=len(candidate.nodes),
        n_wells=len(candidate.wells),
    )


def check_physics(
    candidate: RawModelOutput,
    *,
    schedule: Schedule,
    reference: RawModelOutput | None = None,
    reference_schedule: Schedule | None = None,
    lam: Lambda | None = None,
    oil_density_t_per_m3: float = DEFAULT_OIL_DENSITY_T_PER_M3,
    bhp_limits: BhpLimits | None = None,
    zero_tolerance: float = DEFAULT_ZERO_TOLERANCE,
    watercut_tolerance: float = DEFAULT_WATERCUT_TOLERANCE,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    max_examples: int = DEFAULT_MAX_EXAMPLES_PER_INVARIANT,
) -> PhysicsReport:
    """Все семь инвариантов одним вызовом.

    Без ``reference``/``lam`` differential-инварианты уходят в ``skipped``, и
    отчёт перестаёт быть ``complete`` — значит, ``admissible`` тоже ложно, и
    кандидат в OPM-пакет не попадёт. Это намеренно: пропуск проверки не
    должен быть дешевле её прохождения.
    """

    single = check_prediction(
        candidate,
        schedule=schedule,
        oil_density_t_per_m3=oil_density_t_per_m3,
        bhp_limits=bhp_limits,
        zero_tolerance=zero_tolerance,
        watercut_tolerance=watercut_tolerance,
        max_examples=max_examples,
    )
    if reference is None or reference_schedule is None or lam is None:
        absent = "опора" if reference is None or reference_schedule is None else "λ"
        return PhysicsReport(
            counts=single.counts,
            examples=single.examples,
            evaluated=single.evaluated,
            skipped={
                **single.skipped,
                **{
                    invariant.value: f"не передана {absent}: инвариант не определён"
                    for invariant in _DIFFERENTIAL_INVARIANTS
                },
            },
            n_nodes=single.n_nodes,
            n_wells=single.n_wells,
        )

    pair = check_pair(
        reference,
        candidate,
        reference_schedule=reference_schedule,
        candidate_schedule=schedule,
        lam=lam,
        oil_density_t_per_m3=oil_density_t_per_m3,
        relative_tolerance=relative_tolerance,
        max_examples=max_examples,
    )
    counts = dict(single.counts)
    for name, count in pair.counts.items():
        counts[name] = counts.get(name, 0) + count
    # Одиночный отчёт всегда помечает differential-инварианты пропущенными.
    # Пометку снимает только парная проверка, и только та, что действительно
    # их посчитала: на неидентифицируемой паре ``check_pair`` возвращает
    # собственную причину пропуска, и она должна дойти до отчёта.
    skipped = {
        name: reason
        for name, reason in single.skipped.items()
        if Invariant(name) not in _DIFFERENTIAL_INVARIANTS
    }
    skipped.update(pair.skipped)
    return PhysicsReport(
        counts=counts,
        examples=single.examples + pair.examples,
        evaluated=single.evaluated + pair.evaluated,
        skipped=skipped,
        n_nodes=single.n_nodes,
        n_wells=single.n_wells,
    )


def _require_same_axis(raw: RawModelOutput, schedule: Schedule) -> None:
    if set(raw.wells) != set(schedule.meta.wells):
        raise PhysicsCheckError(
            "ось скважин прогноза не совпадает с расписанием: "
            f"{len(raw.wells)} против {len(schedule.meta.wells)}"
        )


def _scaled_tolerance(magnitude: float, relative_tolerance: float) -> float:
    return abs(magnitude) * relative_tolerance


def _horizon_delta(
    reference: RawModelOutput, candidate: RawModelOutput, channel: str
) -> dict[str, float]:
    """Накопленный за 224 интервала прирост канала, кандидат минус опора."""

    totals: dict[str, float] = {well: 0.0 for well in candidate.wells}
    for node in candidate.nodes:
        totals[node.well] += getattr(node, channel)
    for node in reference.nodes:
        totals[node.well] -= getattr(node, channel)
    return totals


def _check_non_negative(
    node: RawWellStepPrediction, *, sink: _FlagSink, tolerance: float
) -> None:
    for channel in _RATE_CHANNELS + _VOLUME_CHANNELS + ("bhp",):
        value = getattr(node, channel)
        if not math.isfinite(value):
            sink.add(
                Invariant.NON_NEGATIVE,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel} не конечно",
            )
        elif value < -tolerance:
            sink.add(
                Invariant.NON_NEGATIVE,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel} отрицательно",
            )


def _check_watercut(
    node: RawWellStepPrediction,
    *,
    sink: _FlagSink,
    oil_density_t_per_m3: float,
    zero_tolerance: float,
    watercut_tolerance: float,
) -> None:
    """0 ≤ обводнённость ≤ 1 — то же самое, что 0 ≤ нефть ≤ жидкость × плотность.

    Модель отдаёт массу нефти и объём жидкости, обводнённость выводится как
    ``1 − V_нефти / V_жидкости`` (``model.py:_watercut_row``). Тождество
    параметризации проверяется в тех единицах, в которых прогноз пришёл:
    отдельного канала обводнённости в ``RawWellStepPrediction`` нет, и
    вводить его здесь значило бы проверять не то, что уходит в экономику.
    """

    liquid = node.liquid_volume_delta
    oil_volume = node.oil_mass_delta / oil_density_t_per_m3
    if liquid <= zero_tolerance:
        # Нет жидкости — обводнённость не определена; нефть без жидкости
        # означала бы отрицательную обводнённость, и это нарушение.
        if oil_volume > zero_tolerance:
            sink.add(
                Invariant.WATERCUT_RANGE,
                well=node.well,
                control_step=node.control_step,
                observed=oil_volume,
                limit=0.0,
                detail="нефть без жидкости: обводнённость не определена и меньше нуля",
            )
        return
    watercut = 1.0 - oil_volume / liquid
    if watercut < -watercut_tolerance:
        sink.add(
            Invariant.WATERCUT_RANGE,
            well=node.well,
            control_step=node.control_step,
            observed=watercut,
            limit=0.0,
            detail=(
                f"нефти {oil_volume:.3f} м³ при жидкости {liquid:.3f} м³: "
                f"обводнённость {watercut:.6f} меньше нуля"
            ),
        )
    elif watercut > 1.0 + watercut_tolerance:
        sink.add(
            Invariant.WATERCUT_RANGE,
            well=node.well,
            control_step=node.control_step,
            observed=watercut,
            limit=1.0,
            detail=f"обводнённость {watercut:.6f} больше единицы: добыча нефти отрицательна",
        )


def _check_cumulative(
    node: RawWellStepPrediction, *, sink: _FlagSink, tolerance: float
) -> None:
    """Приросты накопленных за интервал величин не убывают.

    Накопленная добыча монотонна по построению, поэтому её прирост на
    интервале неотрицателен. Отрицательный прирост в измеренных целях
    встречается — это перетоки, артефакт разбора UNSMRY, — но предсказывать
    его контракт запрещает (`model.py`, комментарий к `_WATERCUT_CEILING`).
    """

    for channel in _VOLUME_CHANNELS:
        value = getattr(node, channel)
        if math.isfinite(value) and value < -tolerance:
            sink.add(
                Invariant.CUMULATIVE_MONOTONIC,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"{channel}: накопленная величина убывает на интервале",
            )


def _check_shut_well(
    node: RawWellStepPrediction, *, sink: _FlagSink, timeline: object, tolerance: float
) -> None:
    """Невведённая или закрытая скважина не даёт ни дебита, ни объёма."""

    commissioned = timeline.is_commissioned(node.control_step)  # type: ignore[attr-defined]
    status = timeline.operating_status(node.control_step)  # type: ignore[attr-defined]
    if commissioned and status is OperatingStatus.OPEN:
        return
    reason = "не введена" if not commissioned else "закрыта"
    for channel in _RATE_CHANNELS + _VOLUME_CHANNELS:
        value = getattr(node, channel)
        if math.isfinite(value) and abs(value) > tolerance:
            sink.add(
                Invariant.SHUT_WELL_FLOW,
                well=node.well,
                control_step=node.control_step,
                observed=value,
                limit=0.0,
                detail=f"скважина {reason}, а {channel} не ноль",
            )


def _check_bhp(
    node: RawWellStepPrediction, *, sink: _FlagSink, role: Role, limits: BhpLimits
) -> None:
    """Забойное внутри пределов дека: добывающая — пол, нагнетательная — потолок."""

    if role is Role.PROD:
        floor = limits.floor_for(node.well)
        if floor is not None and node.bhp < floor:
            sink.add(
                Invariant.BHP_LIMIT,
                well=node.well,
                control_step=node.control_step,
                observed=node.bhp,
                limit=floor,
                detail=f"забойное {node.bhp:.2f} бар ниже пола добывающей {floor:.2f} бар",
            )
    elif role is Role.INJ:
        ceiling = limits.ceiling_for(node.well)
        if ceiling is not None and node.bhp > ceiling:
            sink.add(
                Invariant.BHP_LIMIT,
                well=node.well,
                control_step=node.control_step,
                observed=node.bhp,
                limit=ceiling,
                detail=(
                    f"забойное {node.bhp:.2f} бар выше потолка нагнетательной "
                    f"{ceiling:.2f} бар"
                ),
            )


__all__ = [
    "BhpLimits",
    "DEFAULT_MAX_EXAMPLES_PER_INVARIANT",
    "DEFAULT_OIL_DENSITY_T_PER_M3",
    "DEFAULT_RELATIVE_TOLERANCE",
    "DEFAULT_WATERCUT_TOLERANCE",
    "DEFAULT_ZERO_TOLERANCE",
    "FORMAT",
    "Invariant",
    "PhysicsCheckError",
    "PhysicsFlag",
    "PhysicsReport",
    "Severity",
    "check_pair",
    "injection_only_pair",
    "lambda_column_sums",
    "check_physics",
    "check_prediction",
    "severity_of",
]
