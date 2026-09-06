"""Обратимость emit→parse на эталонном расписании — известный разрыв.

Организаторы считают наш `wells_schedule.inc` один раз и сравнивают ЧДД с
заявленным; повторных попыток нет. Значит файл обязан означать ровно то
расписание, чей ЧДД заявлен, и разрыв между ними — риск дисквалификации, а не
косметика.

Сегодня разрыв есть, и он воспроизводится **на самом эталоне организаторов**:
эмиссия и обратный разбор теряют двадцать управляющих событий — десять пар
`(SET_LRAT 0.0, OPEN)` на скважинах в момент перевода под закачку.

Корень в `_group_controls`: на шаге с `CONVERT_INJ` у скважины есть пара до
перевода (уставка отбора и статус) и пара после (уставка закачки и статус), а
берутся `targets[-1]` и `statuses[-1]` — только последняя. Строка `WCONPROD`
для такой скважины не пишется вовсе.

Физический смысл, судя по совпадению ЧДД с независимыми прогонами, при этом
сохраняется: «открыть добывающую с нулевым дебитом» эквивалентно закрытой, а
`WCONINJE` в семантике дека и так вытесняет добывающее управление. Но
канонический хеш меняется, и цепочка провенанса рвётся.

Тест **фиксирует текущее поведение, а не одобряет его**. Он существует, чтобы
разрыв нельзя было забыть и чтобы его исчезновение было замечено: когда
эмиттер починят, тест упадёт и его надо будет перевести в проверку
обратимости.
"""

from __future__ import annotations

import collections
import tempfile
from pathlib import Path

import pytest

import conftest
from bridge.opm_deck import OpmDeckEmitter
from contracts import ControlEvent, EventKind, hash_schedule
from schedule import canonicalize
from schedule.build import load_schedule

_LOST_EVENTS = 20
_LOST_KINDS = {EventKind.SET_LRAT.value: 10, EventKind.OPEN.value: 10}


def _key(event: ControlEvent) -> tuple[object, ...]:
    return (
        event.control_step,
        event.well,
        event.kind.value,
        None if event.value is None else round(event.value, 6),
    )


@pytest.fixture(scope="module")
def round_trip():
    """Эталон организаторов, пропущенный через эмиссию и обратный разбор."""

    model_dir = conftest.model_z_dir()
    if model_dir is None or not (model_dir / "Model_Z_sch.inc").is_file():
        pytest.skip("дек Model_Z недоступен")
    source = canonicalize(load_schedule(model_dir / "Model_Z_sch.inc"))
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        emitter.emit(source, Path(scratch) / "deck")
        emitted = canonicalize(
            load_schedule(Path(scratch) / "deck" / "Model_Z_sch.inc")
        )
    return source, emitted


def test_round_trip_loses_exactly_the_conversion_step_producer_pairs(round_trip):
    """Теряются ровно пары уставка+статус добывающей на шаге перевода."""

    source, emitted = round_trip
    lost = collections.Counter(_key(e) for e in source.control_events) - collections.Counter(
        _key(e) for e in emitted.control_events
    )
    extra = collections.Counter(
        _key(e) for e in emitted.control_events
    ) - collections.Counter(_key(e) for e in source.control_events)

    assert sum(extra.values()) == 0, "эмиссия не должна добавлять событий"
    assert sum(lost.values()) == _LOST_EVENTS
    assert collections.Counter(key[2] for key in lost.elements()) == _LOST_KINDS
    # Все потери — уставка нулевого отбора, то есть «открыта, но не течёт».
    for step, well, kind, value in lost:
        if kind == EventKind.SET_LRAT.value:
            assert value == 0.0, f"потеряна ненулевая уставка {well}@{step}: {value}"


def test_round_trip_changes_the_canonical_hash(round_trip):
    """Хеш файла не равен хешу расписания, из которого он собран.

    Пока это так, манифест сдачи обязан нести оба хеша и называть разрыв:
    заявлять хеш объекта в памяти, которого в файле нет, нельзя.
    """

    source, emitted = round_trip

    assert hash_schedule(emitted) != hash_schedule(source)


def test_everything_except_control_events_survives(round_trip):
    """Разрыв ограничен управляющим слоем: фонд и фиксированный слой целы."""

    source, emitted = round_trip

    assert emitted.meta.wells == source.meta.wells
    assert len(emitted.fixed_deck_events) == len(source.fixed_deck_events)
    assert set(emitted.initial_state) == set(source.initial_state)
