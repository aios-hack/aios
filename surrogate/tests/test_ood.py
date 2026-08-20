"""Приёмка задачи 35 (docs/v1/assignments/andrey.md, docs/context/08_contracts.md §5.2).

Карточка: «Детектор выхода за обучающий диапазон — **возвращается вместе с
прогнозом всегда, не опцией**».

Приёмка распадается на три части:

1. **Форма выхода.** Прогноз без оценки собрать нечем — это проверяется
   конструктором `ScoredPrediction`, а не тем, что кто-то помнит позвать
   детектор.
2. **Оценка возвращается всегда.** Точка внутри области получает `0.0`, а
   не `None`: «оценки нет» и «оценка ноль» — разные вещи.
3. **Оценка что-то ловит.** Расписание с уставками вне обучающего диапазона
   обязано получить положительную оценку, с невиданным состоянием — `inf`,
   а сдвиг одной скважины из многих не имеет права раствориться в среднем.

Область строится на настоящих `SurrogateInput` из фичеризатора задачи 32,
не на выдуманных структурах: детектор обязан работать с тем пространством
признаков, которым модель кормится.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from contracts import (
    N_INTERVALS,
    Availability,
    ControlEvent,
    FixedDeckEvent,
    Lambda,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)

from surrogate.features import FeatureContext, HistoryTargets, ScheduleFeatureizer
from surrogate.ood import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    Exceedance,
    FeatureRange,
    OodError,
    OodScore,
    ScoredPrediction,
    fit_domain,
    predict_with_score,
    score,
    worst_offenders,
)
from surrogate.raw_model_output import RawModelOutput, RawWellStepPrediction


def _lambda() -> Lambda:
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2007, 12, 31),
        producers=("P",),
        injectors=("I",),
        matrix=((0.25,),),
        lag_months=1,
        amplitude=0.1,
        stability=0.9,
        rank=1,
        condition_number=1.0,
        achievability_ok={"I": True},
    )


def _schedule(
    *,
    producer_setpoint: float = 10.0,
    injector_setpoint: float = 20.0,
    producer_availability: Availability = Availability.AVAILABLE,
    producer_status: OperatingStatus = OperatingStatus.OPEN,
    control_events: tuple[ControlEvent, ...] = (),
) -> Schedule:
    # Невведённая скважина нормализована контрактом (`contracts/schedule.py`,
    # аудит 14.08): role=NONE, status=SHUT, setpoint=0.0 — иначе два
    # корректных сериализатора дадут разные байты. Выводим их из
    # доступности, а не принимаем отдельными аргументами.
    commissioned = producer_availability is Availability.AVAILABLE
    producer_role = Role.PROD if commissioned else Role.NONE
    if not commissioned:
        producer_status = OperatingStatus.SHUT
        producer_setpoint = 0.0
    return Schedule(
        meta=ScheduleMeta(
            n_control_dates=3,
            n_intervals=2,
            wells=("P", "I"),
            history_prefix_hash="history",
        ),
        initial_state={
            "P": WellState(
                producer_availability, producer_role, producer_status, producer_setpoint
            ),
            "I": WellState(
                Availability.AVAILABLE, Role.INJ, OperatingStatus.OPEN, injector_setpoint
            ),
        },
        fixed_deck_events=(
            FixedDeckEvent(
                control_step=0,
                well="P",
                operator="COMPDAT",
                raw_args=("1", "1", "1", "1", "OPEN"),
            ),
        ),
        control_events=control_events,
    )


def _context(
    *,
    producer_static: dict[str, float] | None = None,
    injector_static: dict[str, float] | None = None,
) -> FeatureContext:
    """Набор имён статических признаков обязан совпадать у всех скважин —
    это требование фичеризатора задачи 32, поэтому имена меняются сразу
    обеим, а различаются только значения."""

    return FeatureContext(
        control_dates=(date(2007, 1, 1), date(2007, 2, 1), date(2007, 3, 1)),
        history_start=date(1994, 11, 1),
        history_prefix_hash="history",
        history_targets={
            "P": HistoryTargets(1_000.0, 0.0, 3),
            "I": HistoryTargets(0.0, 2_000.0, 4),
        },
        static_features={
            "P": producer_static or {"i": 10.0, "j": 20.0},
            "I": injector_static or {"i": 11.0, "j": 21.0},
        },
        lambda_windows=(_lambda(),),
    )


def _input(**kwargs):
    context = kwargs.pop("context", None) or _context()
    return ScheduleFeatureizer().transform(_schedule(**kwargs), context)


def _training_domain():
    """Обучающая область по трём расписаниям с уставками 10…30."""

    return fit_domain(
        [
            _input(producer_setpoint=10.0, injector_setpoint=20.0),
            _input(producer_setpoint=20.0, injector_setpoint=25.0),
            _input(producer_setpoint=30.0, injector_setpoint=30.0),
        ]
    )


def _raw_output(candidate, wells: tuple[str, ...] = ("P", "I")) -> RawModelOutput:
    """`RawModelOutput` требует полное покрытие всех 224 интервалов — тот же
    инвариант, что у адаптера задачи 33; сокращать его тут нельзя."""

    return RawModelOutput(
        canonical_schedule_hash=candidate.canonical_schedule_hash,
        wells=wells,
        nodes=tuple(
            RawWellStepPrediction(
                well=well,
                control_step=step,
                oil_mass_delta=1.0,
                liquid_volume_delta=2.0,
                injection_volume_delta=0.0,
                liquid_rate=3.0,
                injection_rate=0.0,
                bhp=100.0,
            )
            for well in wells
            for step in range(N_INTERVALS)
        ),
    )


# --- 1. Форма выхода: оценка не опция --------------------------------------


def test_prediction_cannot_be_built_without_a_score() -> None:
    """Главное требование §5.2, выраженное типом: у `ScoredPrediction` оба
    поля обязательны, значения по умолчанию нет — прогноз без оценки не
    собирается вовсе."""

    candidate = _input()
    with pytest.raises(TypeError):
        ScoredPrediction(output=_raw_output(candidate))  # type: ignore[call-arg]


def test_predict_with_score_is_the_only_door_and_it_always_scores() -> None:
    domain = _training_domain()
    candidate = _input(producer_setpoint=15.0)

    scored = predict_with_score(_raw_output(candidate), candidate, domain)

    assert isinstance(scored, ScoredPrediction)
    assert isinstance(scored.ood, OodScore)
    assert scored.output is not None


def test_score_is_zero_not_none_inside_the_domain() -> None:
    """«Оценки нет» и «оценка ноль» — разные вещи, и потребитель не должен
    различать их по `is None`."""

    domain = _training_domain()
    assessment = score(_input(producer_setpoint=15.0), domain)

    assert assessment.score == 0.0
    assert assessment.exceedances == ()
    assert assessment.worst is None
    assert assessment.inside(tau=0.0) is True


# --- 2. Что детектор ловит -------------------------------------------------


def test_setpoint_far_above_training_is_detected() -> None:
    """Уставка вдвое выше всего, что было в обучении, обязана дать
    положительную оценку с указанием признака и скважины."""

    domain = _training_domain()
    assessment = score(_input(producer_setpoint=200.0), domain)

    assert assessment.score > 0.0
    worst = assessment.worst
    assert worst is not None
    assert worst.well == "P"
    assert worst.value == pytest.approx(200.0)
    assert worst.feature in NUMERIC_FEATURES


def test_exceedance_is_measured_in_widths_of_the_training_interval() -> None:
    """Оценка безразмерна: выход на ширину интервала даёт 1.0, независимо
    от того, в чём признак измеряется."""

    interval = FeatureRange(name="x", low=10.0, high=30.0)

    assert interval.exceedance(30.0) == 0.0
    assert interval.exceedance(50.0) == pytest.approx(1.0)
    assert interval.exceedance(70.0) == pytest.approx(2.0)
    assert interval.exceedance(0.0) == pytest.approx(0.5)


def test_unseen_categorical_value_is_infinite_not_far() -> None:
    """Между значениями перечисления расстояния нет: невиданное состояние —
    это «вне области», а не «далеко от неё», и никакой конечный τ его
    пропустить не должен."""

    domain = fit_domain([_input(producer_setpoint=10.0)])
    candidate = _input(
        producer_setpoint=10.0,
        producer_availability=Availability.NOT_COMMISSIONED,
        producer_status=OperatingStatus.SHUT,
    )

    assessment = score(candidate, domain)

    assert assessment.score == math.inf
    assert assessment.inside(tau=1e12) is False
    assert assessment.worst is not None
    assert assessment.worst.feature in CATEGORICAL_FEATURES


def test_degenerate_feature_admits_only_the_value_it_saw() -> None:
    """Признак, у которого в обучении было одно значение, ширины не имеет.
    Подобранный эпсилон был бы выдумкой: обучающая выборка про соседние
    значения действительно ничего не знает."""

    interval = FeatureRange(name="x", low=7.0, high=7.0)

    assert interval.degenerate is True
    assert interval.exceedance(7.0) == 0.0
    assert interval.exceedance(7.000001) == math.inf


def test_one_well_out_of_range_does_not_dissolve_in_the_average() -> None:
    """Ключевое свойство агрегирования: экстраполяция по одной скважине при
    усреднении растворилась бы в нулях остальных, и кандидат выглядел бы
    «внутри области». Оценка — максимум, поэтому не растворяется."""

    domain = _training_domain()
    candidate = _input(producer_setpoint=500.0)  # I остаётся внутри диапазона

    assessment = score(candidate, domain)
    offending_wells = {item.well for item in assessment.exceedances}

    assert assessment.score > 1.0
    assert offending_wells == {"P"}

    # Оценка равна худшему выходу и только ему.
    assert assessment.score == max(item.score for item in assessment.exceedances)

    # Среднее по всем проверкам уже здесь ниже максимума, а разбавление
    # растёт с размером фонда: в Model_Z скважин 103, а не 2, и одна
    # экстраполирующая при усреднении дала бы сотую долю порога.
    checks = assessment.n_nodes * (len(NUMERIC_FEATURES) + 2)
    mean_like = sum(item.score for item in assessment.exceedances) / checks

    assert mean_like < assessment.score


def test_worst_offenders_are_ordered_by_severity() -> None:
    """Цикл верификации обязан уметь сказать не только «кандидат вне
    области», но и что именно его туда вывело."""

    domain = _training_domain()
    assessment = score(_input(producer_setpoint=400.0), domain)

    top = worst_offenders(assessment, limit=3)

    assert top
    assert list(top) == sorted(top, key=lambda item: -item.score)
    assert all(isinstance(item, Exceedance) for item in top)


# --- 3. Область доверия §10.2 ----------------------------------------------


def test_trust_region_is_a_threshold_on_the_score() -> None:
    """«Кандидат допустим, пока `ood_score ≤ τ`» (§10.2). Расширение и
    сужение области доверия — движение τ, отдельного механизма нет."""

    domain = _training_domain()
    assessment = score(_input(producer_setpoint=200.0), domain)

    assert assessment.inside(tau=assessment.score) is True
    assert assessment.inside(tau=assessment.score / 2.0) is False
    assert assessment.inside(tau=assessment.score * 2.0) is True


def test_negative_tau_is_rejected() -> None:
    domain = _training_domain()
    assessment = score(_input(producer_setpoint=15.0), domain)

    with pytest.raises(OodError):
        assessment.inside(tau=-0.1)


# --- Провенанс и отказы вместо правдоподобных чисел ------------------------


def test_domain_carries_the_schedule_hashes_it_was_measured_on() -> None:
    """Область, замеренная на одном датасете, не описывает другой:
    `OptimizerResult.provenance` обязан уметь связать `ood_score` с версией
    данных (§6.1)."""

    inputs = [_input(producer_setpoint=10.0), _input(producer_setpoint=20.0)]
    domain = fit_domain(inputs)

    assert domain.schedule_hashes == tuple(item.canonical_schedule_hash for item in inputs)
    assert domain.n_nodes > 0


def test_static_features_are_part_of_the_domain() -> None:
    """Статика скважины входит в признаки (задача 32), значит и в область:
    скважина с невиданной геометрией — тоже выход за диапазон."""

    domain = fit_domain([_input(context=_context(producer_static={"i": 10.0, "j": 20.0}))])
    candidate = _input(context=_context(producer_static={"i": 999.0, "j": 20.0}))

    assessment = score(candidate, domain)

    assert assessment.score > 0.0
    assert any(item.feature.startswith("static:") for item in assessment.exceedances)


def test_empty_training_set_is_rejected() -> None:
    """Моков нет: пустая выборка не даёт «пустую область, всё внутри»."""

    with pytest.raises(OodError):
        fit_domain([])


def test_mismatched_static_feature_names_are_rejected() -> None:
    """Область и кандидат обязаны жить в одном пространстве признаков;
    молчаливое выравнивание по позиции сравнивало бы разные величины."""

    domain = fit_domain([_input(context=_context())])
    renamed = _context(
        producer_static={"i": 1.0, "k": 2.0},
        injector_static={"i": 1.0, "k": 2.0},
    )
    candidate = _input(context=renamed)

    with pytest.raises(OodError):
        score(candidate, domain)


def test_domain_over_inconsistent_static_names_is_rejected() -> None:
    first = _input(context=_context())
    second = _input(
        context=_context(
            producer_static={"i": 1.0, "k": 2.0},
            injector_static={"i": 1.0, "k": 2.0},
        )
    )

    with pytest.raises(OodError):
        fit_domain([first, second])


def test_zero_limit_for_offenders_is_rejected() -> None:
    domain = _training_domain()
    assessment = score(_input(producer_setpoint=15.0), domain)

    with pytest.raises(OodError):
        worst_offenders(assessment, limit=0)
