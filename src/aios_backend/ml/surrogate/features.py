"""Feature construction for task 32.

The featureizer deliberately has no response/simulator argument.  Dynamic
features are derived from one :class:`contracts.Schedule`; the only other
inputs are immutable deck-derived context (calendar, history prefix and well
static data) and measured, date-scoped ``Lambda`` matrices.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping, Sequence

from aios_backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    Lambda,
    OperatingStatus,
    Role,
    Schedule,
    T0,
    WellState,
    hash_schedule,
)


_TOKEN_RE = re.compile(rb"'([^']*)'|([^\s/]+)")
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_EVENT_ORDER = {
    # A conversion batch contains the old producer's zero LRAT and the new
    # injector's RATE at one control step.  Apply the close while the well is
    # still PROD, then change role, then apply the injector target.  The
    # canonical/hash order puts CONVERT_INJ first, but that serialization
    # order is not a valid state-transition order for feature construction.
    EventKind.SET_LRAT: 0,
    EventKind.CONVERT_INJ: 1,
    EventKind.SET_RATE: 2,
    EventKind.OPEN: 3,
    EventKind.SHUT: 3,
}


class FeatureError(ValueError):
    """The schedule/context cannot produce unambiguous surrogate features."""


@dataclass(frozen=True, slots=True)
class HistoryTargets:
    """Deck-derived target state immediately before ``Schedule.meta.t0``.

    These are target, not simulated, volumes.  They are explicit because the
    canonical Schedule intentionally stores the immutable 1994--2006 prefix
    only by hash.
    """

    target_liquid_m3: float
    target_injection_m3: float
    event_count: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_liquid_m3) or not math.isfinite(
            self.target_injection_m3
        ):
            raise FeatureError("исторические целевые накопления должны быть конечными")
        if self.target_liquid_m3 < 0 or self.target_injection_m3 < 0:
            raise FeatureError("исторические целевые накопления не могут быть отрицательными")
        if self.event_count < 0:
            raise FeatureError("историческое число событий не может быть отрицательным")


@dataclass(frozen=True, slots=True)
class FeatureContext:
    """Immutable non-simulator inputs shared by all candidate schedules."""

    control_dates: tuple[date, ...]
    history_start: date
    history_prefix_hash: str
    history_targets: Mapping[str, HistoryTargets]
    static_features: Mapping[str, Mapping[str, float]]
    lambda_windows: tuple[Lambda, ...]


@dataclass(frozen=True, slots=True)
class WellStepFeatures:
    """One node of the ``control_step × well`` feature tensor."""

    control_step: int
    interval_start: date
    interval_end: date
    well: str
    availability: Availability
    role: Role
    operating_status: OperatingStatus
    setpoint_m3_per_day: float
    effective_target_rate_m3_per_day: float
    cumulative_target_liquid_m3: float
    cumulative_target_injection_m3: float
    cumulative_neighbor_injection_m3: float
    current_neighbor_injection_m3_per_day: float
    event_count: int
    fixed_event_count: int
    static_values: tuple[float, ...]
    lambda_window_start: date
    lambda_window_end: date


@dataclass(frozen=True, slots=True)
class LambdaEdgeFeature:
    """A full measured producer<-injector edge for its applicable window."""

    control_step: int
    producer: str
    injector: str
    coefficient: float
    injector_target_rate_m3_per_day: float
    injector_cumulative_target_injection_m3: float
    weighted_target_rate_m3_per_day: float
    weighted_cumulative_target_injection_m3: float


@dataclass(frozen=True, slots=True)
class SurrogateInput:
    """Deterministic full-trajectory input; contains no simulated response."""

    canonical_schedule_hash: str
    wells: tuple[str, ...]
    static_feature_names: tuple[str, ...]
    nodes: tuple[WellStepFeatures, ...]
    lambda_edges: tuple[LambdaEdgeFeature, ...]


@dataclass(slots=True)
class _MutableState:
    availability: Availability
    role: Role
    operating_status: OperatingStatus
    setpoint: float

    @classmethod
    def from_contract(cls, state: WellState) -> _MutableState:
        return cls(
            availability=state.availability,
            role=state.role,
            operating_status=state.operating_status,
            setpoint=state.setpoint,
        )

    @property
    def effective_target(self) -> float:
        if (
            self.availability is Availability.AVAILABLE
            and self.operating_status is OperatingStatus.OPEN
        ):
            return self.setpoint
        return 0.0


def _records(raw_block: bytes) -> list[tuple[str, ...]]:
    records: list[tuple[str, ...]] = []
    for line in raw_block.splitlines()[1:-1]:
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise FeatureError(f"запись дека не заканчивается '/': {body!r}")
        fields = []
        for match in _TOKEN_RE.finditer(body[:-1]):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            try:
                fields.append(token.decode("ascii"))
            except UnicodeDecodeError as error:
                raise FeatureError("не-ASCII токен в расписании") from error
        if fields:
            records.append(tuple(fields))
    return records


def _blocks(raw: bytes) -> list[tuple[str, bytes]]:
    lines = raw.splitlines(keepends=True)
    result: list[tuple[str, bytes]] = []
    index = 0
    while index < len(lines):
        try:
            keyword = lines[index].strip().decode("ascii")
        except UnicodeDecodeError:
            index += 1
            continue
        if keyword not in {"DATES", "WCONPROD", "WCONINJE"}:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() != b"/":
            end += 1
        if end == len(lines):
            raise FeatureError(f"{keyword}: незакрытый блок")
        result.append((keyword, b"".join(lines[index : end + 1])))
        index = end + 1
    return result


def _deck_date(raw_block: bytes) -> date:
    records = _records(raw_block)
    if len(records) != 1 or len(records[0]) != 3:
        raise FeatureError("DATES должен содержать ровно одну дату")
    day, month, year = records[0]
    try:
        return date(int(year), _MONTHS[month.upper()], int(day))
    except (KeyError, ValueError) as error:
        raise FeatureError(f"некорректная дата: {records[0]!r}") from error


def _status(value: str) -> OperatingStatus:
    try:
        return OperatingStatus[value]
    except KeyError as error:
        raise FeatureError(f"неизвестный статус скважины {value!r}") from error


def _float(value: str, *, well: str) -> float:
    try:
        result = float(value)
    except ValueError as error:
        raise FeatureError(f"уставка {well!r} не является числом: {value!r}") from error
    if not math.isfinite(result) or result < 0:
        raise FeatureError(f"некорректная уставка {well!r}: {value!r}")
    return result


def _state_from_wcon(keyword: str, record: tuple[str, ...]) -> tuple[str, _MutableState]:
    well = record[0]
    if keyword == "WCONPROD":
        if len(record) < 7 or record[2] != "LRAT":
            raise FeatureError(f"WCONPROD {well!r}: ожидается режим LRAT")
        return well, _MutableState(
            Availability.AVAILABLE,
            Role.PROD,
            _status(record[1]),
            _float(record[6], well=well),
        )
    if len(record) < 5 or record[1] != "WATER" or record[3] != "RATE":
        raise FeatureError(f"WCONINJE {well!r}: ожидается WATER/RATE")
    return well, _MutableState(
        Availability.AVAILABLE,
        Role.INJ,
        _status(record[2]),
        _float(record[4], well=well),
    )


def history_targets_from_deck(
    raw_schedule: bytes,
    wells: Sequence[str],
    *,
    t0: date = T0,
) -> tuple[date, Mapping[str, HistoryTargets]]:
    """Integrate target rates in the immutable deck prefix, without OPM.

    The first DATES record is the start of target accumulation (01.11.1994
    for Model_Z).  Events at ``t0`` are intentionally excluded: they belong
    to the two-layer Schedule and are applied by :class:`ScheduleFeatureizer`.
    """

    ordered_wells = tuple(wells)
    if len(set(ordered_wells)) != len(ordered_wells):
        raise FeatureError("ось wells содержит дубликаты")
    states: dict[str, _MutableState] = {
        well: _MutableState(
            Availability.NOT_COMMISSIONED,
            Role.NONE,
            OperatingStatus.SHUT,
            0.0,
        )
        for well in ordered_wells
    }
    liquid = {well: 0.0 for well in ordered_wells}
    injection = {well: 0.0 for well in ordered_wells}
    event_count = {well: 0 for well in ordered_wells}
    history_start: date | None = None
    current_date: date | None = None

    for keyword, raw_block in _blocks(raw_schedule):
        if keyword == "DATES":
            next_date = _deck_date(raw_block)
            if history_start is None:
                history_start = next_date
            if current_date is not None:
                if next_date <= current_date:
                    raise FeatureError(f"DATES не возрастают: {current_date} -> {next_date}")
                interval_end = min(next_date, t0)
                if interval_end > current_date:
                    days = (interval_end - current_date).days
                    for well, state in states.items():
                        target = state.effective_target * days
                        if state.role is Role.PROD:
                            liquid[well] += target
                        elif state.role is Role.INJ:
                            injection[well] += target
            current_date = next_date
            if next_date >= t0:
                break
            continue

        if current_date is None or current_date >= t0:
            continue
        for record in _records(raw_block):
            well, state = _state_from_wcon(keyword, record)
            if well not in states:
                raise FeatureError(f"скважина {well!r} из истории отсутствует в оси wells")
            states[well] = state
            event_count[well] += 1

    if history_start is None:
        raise FeatureError("в деке нет DATES")
    if current_date is None or current_date < t0:
        raise FeatureError(f"дек не достигает t0={t0.isoformat()}")
    return history_start, MappingProxyType(
        {
            well: HistoryTargets(liquid[well], injection[well], event_count[well])
            for well in ordered_wells
        }
    )


def _commissioning_state(event_operator: str, raw_args: tuple[str, ...]) -> _MutableState:
    if event_operator == "WCONPROD":
        return _state_from_wcon(event_operator, ("<fixed>", *raw_args))[1]
    if event_operator == "WCONINJE":
        return _state_from_wcon(event_operator, ("<fixed>", *raw_args))[1]
    raise FeatureError(f"{event_operator}: не является событием ввода")


def _apply_control(state: _MutableState, event: ControlEvent) -> None:
    if state.availability is Availability.NOT_COMMISSIONED:
        raise FeatureError(
            f"control_step={event.control_step}, well={event.well!r}: управление до ввода"
        )
    if event.kind is EventKind.CONVERT_INJ:
        if state.role is not Role.PROD:
            raise FeatureError(f"{event.well!r}: CONVERT_INJ применён не к PROD")
        state.role = Role.INJ
    elif event.kind is EventKind.SET_LRAT:
        if state.role is not Role.PROD:
            raise FeatureError(f"{event.well!r}: SET_LRAT применён не к PROD")
        state.setpoint = event.value if event.value is not None else 0.0
    elif event.kind is EventKind.SET_RATE:
        if state.role is not Role.INJ:
            raise FeatureError(f"{event.well!r}: SET_RATE применён не к INJ")
        state.setpoint = event.value if event.value is not None else 0.0
    elif event.kind is EventKind.OPEN:
        state.operating_status = OperatingStatus.OPEN
    elif event.kind is EventKind.SHUT:
        state.operating_status = OperatingStatus.SHUT


class ScheduleFeatureizer:
    """Materialize deterministic full-trajectory surrogate features."""

    def transform(self, schedule: Schedule, context: FeatureContext) -> SurrogateInput:
        wells = tuple(schedule.meta.wells)
        if not wells or len(set(wells)) != len(wells):
            raise FeatureError("Schedule.meta.wells должен быть непустой осью без дубликатов")
        if set(schedule.initial_state) != set(wells):
            raise FeatureError("initial_state должен содержать ровно Schedule.meta.wells")
        if len(context.control_dates) != schedule.meta.n_control_dates:
            raise FeatureError(
                "control_dates должен содержать n_control_dates дат, включая terminal_state"
            )
        if context.control_dates[0] != schedule.meta.t0:
            raise FeatureError("control_dates[0] не совпадает с Schedule.meta.t0")
        if any(right <= left for left, right in zip(context.control_dates, context.control_dates[1:])):
            raise FeatureError("control_dates должны строго возрастать")
        if context.history_start != date(1994, 11, 1):
            raise FeatureError("целевые накопления Model_Z должны начинаться 01.11.1994")
        if context.history_prefix_hash != schedule.meta.history_prefix_hash:
            raise FeatureError("history_targets построены не из префикса этого Schedule")
        if set(context.history_targets) != set(wells):
            raise FeatureError("history_targets должен содержать ровно Schedule.meta.wells")
        if set(context.static_features) != set(wells):
            raise FeatureError("static_features должен содержать ровно Schedule.meta.wells")

        static_names = tuple(sorted(context.static_features[wells[0]]))
        static_values: dict[str, tuple[float, ...]] = {}
        for well in wells:
            values = context.static_features[well]
            if tuple(sorted(values)) != static_names:
                raise FeatureError("набор статических признаков должен совпадать у всех скважин")
            row = tuple(float(values[name]) for name in static_names)
            if not all(math.isfinite(value) for value in row):
                raise FeatureError(f"нечисловая статика у скважины {well!r}")
            static_values[well] = row

        states = {well: _MutableState.from_contract(schedule.initial_state[well]) for well in wells}
        liquid = {
            well: context.history_targets[well].target_liquid_m3 for well in wells
        }
        injection = {
            well: context.history_targets[well].target_injection_m3 for well in wells
        }
        event_count = {well: context.history_targets[well].event_count for well in wells}
        fixed_event_count = {well: 0 for well in wells}

        fixed_by_step: dict[int, list] = {}
        for event in schedule.fixed_deck_events:
            if event.well not in states:
                raise FeatureError(f"неизвестная скважина в fixed_deck_events: {event.well!r}")
            fixed_by_step.setdefault(event.control_step, []).append(event)
        controls_by_step: dict[int, list[ControlEvent]] = {}
        for event in schedule.control_events:
            if event.well not in states:
                raise FeatureError(f"неизвестная скважина в control_events: {event.well!r}")
            controls_by_step.setdefault(event.control_step, []).append(event)

        nodes: list[WellStepFeatures] = []
        edges: list[LambdaEdgeFeature] = []
        for control_step in range(schedule.meta.n_intervals):
            interval_start = context.control_dates[control_step]
            interval_end = context.control_dates[control_step + 1]
            lambda_ = self._lambda_for_date(context.lambda_windows, interval_start)
            self._validate_lambda(lambda_, wells)

            for event in fixed_by_step.get(control_step, ()):
                fixed_event_count[event.well] += 1
                if event.operator in {"WCONPROD", "WCONINJE"}:
                    if states[event.well].availability is Availability.AVAILABLE:
                        raise FeatureError(f"повторный ввод скважины {event.well!r}")
                    states[event.well] = _commissioning_state(event.operator, event.raw_args)
                    event_count[event.well] += 1

            ordered_controls = sorted(
                controls_by_step.get(control_step, ()),
                key=lambda event: (event.well, _EVENT_ORDER[event.kind]),
            )
            for event in ordered_controls:
                _apply_control(states[event.well], event)
                event_count[event.well] += 1

            days = (interval_end - interval_start).days
            for well, state in states.items():
                volume = state.effective_target * days
                if state.role is Role.PROD:
                    liquid[well] += volume
                elif state.role is Role.INJ:
                    injection[well] += volume

            edge_rows: dict[str, list[LambdaEdgeFeature]] = {}
            for producer_index, producer in enumerate(lambda_.producers):
                if (
                    states[producer].availability is Availability.NOT_COMMISSIONED
                    or states[producer].role is not Role.PROD
                ):
                    continue
                for injector_index, injector in enumerate(lambda_.injectors):
                    if (
                        states[injector].availability is Availability.NOT_COMMISSIONED
                        or states[injector].role is not Role.INJ
                    ):
                        continue
                    coefficient = float(lambda_.matrix[producer_index][injector_index])
                    injector_rate = (
                        states[injector].effective_target
                        if states[injector].role is Role.INJ
                        else 0.0
                    )
                    edge = LambdaEdgeFeature(
                        control_step=control_step,
                        producer=producer,
                        injector=injector,
                        coefficient=coefficient,
                        injector_target_rate_m3_per_day=injector_rate,
                        injector_cumulative_target_injection_m3=injection[injector],
                        weighted_target_rate_m3_per_day=coefficient * injector_rate,
                        weighted_cumulative_target_injection_m3=(
                            coefficient * injection[injector]
                        ),
                    )
                    edges.append(edge)
                    edge_rows.setdefault(producer, []).append(edge)

            for well in wells:
                state = states[well]
                neighbor_edges = edge_rows.get(well, ())
                nodes.append(
                    WellStepFeatures(
                        control_step=control_step,
                        interval_start=interval_start,
                        interval_end=interval_end,
                        well=well,
                        availability=state.availability,
                        role=state.role,
                        operating_status=state.operating_status,
                        setpoint_m3_per_day=state.setpoint,
                        effective_target_rate_m3_per_day=state.effective_target,
                        cumulative_target_liquid_m3=liquid[well],
                        cumulative_target_injection_m3=injection[well],
                        cumulative_neighbor_injection_m3=sum(
                            edge.weighted_cumulative_target_injection_m3
                            for edge in neighbor_edges
                        ),
                        current_neighbor_injection_m3_per_day=sum(
                            edge.weighted_target_rate_m3_per_day for edge in neighbor_edges
                        ),
                        event_count=event_count[well],
                        fixed_event_count=fixed_event_count[well],
                        static_values=static_values[well],
                        lambda_window_start=lambda_.window_start,
                        lambda_window_end=lambda_.window_end,
                    )
                )

        return SurrogateInput(
            canonical_schedule_hash=hash_schedule(schedule),
            wells=wells,
            static_feature_names=static_names,
            nodes=tuple(nodes),
            lambda_edges=tuple(edges),
        )

    @staticmethod
    def _lambda_for_date(windows: Sequence[Lambda], on_date: date) -> Lambda:
        matches = [
            lambda_
            for lambda_ in windows
            if lambda_.window_start <= on_date <= lambda_.window_end
        ]
        if len(matches) != 1:
            raise FeatureError(
                f"для {on_date.isoformat()} ожидалось ровно одно окно lambda, найдено {len(matches)}"
            )
        return matches[0]

    @staticmethod
    def _validate_lambda(lambda_: Lambda, wells: tuple[str, ...]) -> None:
        if len(set(lambda_.producers)) != len(lambda_.producers):
            raise FeatureError("lambda.producers содержит дубликаты")
        if len(set(lambda_.injectors)) != len(lambda_.injectors):
            raise FeatureError("lambda.injectors содержит дубликаты")
        unknown = (set(lambda_.producers) | set(lambda_.injectors)) - set(wells)
        if unknown:
            raise FeatureError(f"lambda ссылается на неизвестные скважины: {sorted(unknown)}")
        if len(lambda_.matrix) != len(lambda_.producers) or any(
            len(row) != len(lambda_.injectors) for row in lambda_.matrix
        ):
            raise FeatureError("форма lambda.matrix не совпадает с осями")
        if any(not math.isfinite(value) for row in lambda_.matrix for value in row):
            raise FeatureError("lambda.matrix содержит нечисловое значение")
