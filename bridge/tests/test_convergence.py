"""Приёмка задачи 40 (docs/assignments/andrey.md, docs/context/08_contracts.md §10.4).

Карточка: критерий «прогноз сошёлся» — «**замеряется на данных, а не
выбирается**».

§10.4 держит вопрос открытым: три кандидата — абсолютное отклонение ЧДД,
ранговая согласованность top-k, оба порога сразу — и ни один не замерен.
Поэтому приёмка проверяет не «правильный критерий выбран», а что:

1. все три кандидата §10.4 построены и работают;
2. замер идёт по решению, ради которого критерий существует, — расширять
   область доверия или сжимать;
3. две ошибки разделены: ложное расширение уводит цикл, упущенное только
   замедляет, и в одну величину они не складываются;
4. порог просматривается сеткой целиком, а не назначается точкой;
5. на синтетике вердикт не выносится вовсе.

Таблицы раундов здесь сконструированы с известным ответом: проверяется
измерительный инструмент, а не качество суррогата, которого пока нет.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from contracts import Theta

from bridge.convergence import (
    CalibrationReport,
    ConvergenceError,
    CriterionMeasurement,
    absolute_deviation_criterion,
    both_criterion,
    measure_criteria,
    rank_agreement_criterion,
    trust_was_justified,
)
from bridge.verification import CandidateCheck, RoundReport

ROOT = Path(__file__).resolve().parent.parent


def _theta(value: float) -> Theta:
    return Theta(values={"x": value}, bounds={"x": (0.0, 100.0)})


def _check(
    predicted: float,
    actual: float,
    *,
    round_index: int = 0,
    x: float = 1.0,
) -> CandidateCheck:
    return CandidateCheck(
        round_index=round_index,
        theta=_theta(x),
        predicted_npv=predicted,
        actual_npv=actual,
        ood_score=0.1,
        tau=1.0,
        surrogate_version=1,
        run_id=f"run-{round_index}-{x}",
        canonical_schedule_hash="c" * 64,
    )


def _round(index: int, pairs: list[tuple[float, float]]) -> RoundReport:
    checks = tuple(
        _check(predicted, actual, round_index=index, x=float(position))
        for position, (predicted, actual) in enumerate(pairs)
    )
    return RoundReport(
        index=index,
        tau=1.0,
        next_tau=2.0,
        checks=checks,
        converged=True,
        retrained=False,
        surrogate_version=1,
        optimizer_evaluations=10,
        feasible_candidates=len(checks),
    )


# --- 1. Три кандидата §10.4 -------------------------------------------------


def test_absolute_deviation_criterion_uses_relative_error() -> None:
    """Порог относительный, а не в рублях: ЧДД Model_Z порядка 1e10, и
    рублёвый порог пришлось бы переназначать при смене нормативов."""

    within = [_check(predicted=105.0, actual=100.0)]
    beyond = [_check(predicted=130.0, actual=100.0)]

    criterion = absolute_deviation_criterion(0.1)

    assert criterion(within) is True
    assert criterion(beyond) is False


def test_absolute_deviation_needs_every_candidate_inside() -> None:
    """Один промахнувшийся кандидат снимает сходимость всего раунда:
    расширять область по среднему значило бы усреднить промах."""

    mixed = [_check(101.0, 100.0), _check(300.0, 100.0)]

    assert absolute_deviation_criterion(0.1)(mixed) is False


def test_rank_agreement_criterion_looks_at_order_not_at_values() -> None:
    """Это то, что цикл на самом деле использует: он берёт top-k по
    прогнозу, и важен порядок, а не совпадение чисел (§5.2)."""

    # Числа мимо на порядок, порядок верен.
    shifted = [_check(1_000.0, 10.0), _check(2_000.0, 20.0), _check(3_000.0, 30.0)]
    # Числа близки, порядок перевёрнут.
    reversed_order = [_check(30.0, 10.0), _check(20.0, 20.0), _check(10.0, 30.0)]

    criterion = rank_agreement_criterion(0.9)

    assert criterion(shifted) is True
    assert criterion(reversed_order) is False


def test_rank_agreement_on_a_single_candidate_is_an_error_not_true() -> None:
    """Возвращать True на одном кандидате значило бы объявлять сходимость
    даром — ранговая согласованность одной точки не определена."""

    with pytest.raises(ConvergenceError):
        rank_agreement_criterion(0.5)([_check(1.0, 1.0)])


def test_both_criterion_is_a_conjunction_not_an_average() -> None:
    """Среднее позволило бы отличной корреляции выкупить провальное
    отклонение."""

    good_order_bad_values = [
        _check(1_000.0, 10.0),
        _check(2_000.0, 20.0),
        _check(3_000.0, 30.0),
    ]

    assert rank_agreement_criterion(0.9)(good_order_bad_values) is True
    assert absolute_deviation_criterion(0.1)(good_order_bad_values) is False
    assert both_criterion(0.1, 0.9)(good_order_bad_values) is False


# --- 2. Замер идёт по решению, ради которого критерий существует -----------


def test_trust_is_justified_when_the_predicted_best_is_actually_best() -> None:
    checks = [_check(300.0, 30.0), _check(200.0, 20.0), _check(100.0, 10.0)]

    assert trust_was_justified(checks, regret_tolerance=0.0) is True


def test_trust_is_not_justified_when_the_predicted_best_is_actually_worst() -> None:
    """Ровно та ошибка, ради которой критерий стоит в цикле: суррогат
    поставил первым кандидата, который по факту хуже всех."""

    checks = [_check(300.0, 10.0), _check(200.0, 20.0), _check(100.0, 30.0)]

    assert trust_was_justified(checks, regret_tolerance=0.1) is False


def test_small_shortfall_within_tolerance_still_counts_as_justified() -> None:
    checks = [_check(300.0, 29.0), _check(200.0, 30.0)]

    assert trust_was_justified(checks, regret_tolerance=0.05) is True
    assert trust_was_justified(checks, regret_tolerance=0.01) is False


def test_zero_best_npv_is_an_error_not_a_silent_ratio() -> None:
    with pytest.raises(ConvergenceError):
        trust_was_justified([_check(1.0, 0.0)], regret_tolerance=0.1)


# --- 3. Две ошибки разделены -----------------------------------------------


def test_false_and_missed_expansions_are_counted_separately() -> None:
    """Ложное расширение уводит цикл в зону, где суррогат вводит в
    заблуждение; упущенное только тратит раунд. В одну accuracy они не
    складываются."""

    rounds = [
        # Числа близки (отклонение ≤ 2%), но порядок перевёрнут: критерий по
        # отклонению скажет «сошлось», а суррогат при этом поставил первым
        # кандидата, который по факту худший. Ложное расширение.
        _round(0, [(102.0, 100.0), (101.0, 101.0), (100.0, 102.0)]),
        # Порядок верен, числа мимо на два порядка: доверие оправдано, а
        # критерий по отклонению скажет «разошлось». Упущенное расширение.
        _round(1, [(3_000.0, 30.0), (2_000.0, 20.0), (1_000.0, 10.0)]),
    ]

    report = measure_criteria(rounds, regret_tolerance=0.01)
    deviation = report.sweep_of("absolute_deviation")
    loose = next(m for m in deviation.measurements if m.threshold == 0.05)

    assert loose.false_expansions == 1
    assert loose.missed_expansions == 1
    assert loose.correct_expansions == 0


def test_ranking_prefers_fewer_false_expansions_over_more_correct_ones() -> None:
    """Лексикографика, а не взвешенная сумма: вес означал бы курс обмена
    между «увели цикл» и «потратили раунд», а его никто не замерял."""

    safe = CriterionMeasurement(
        name="a",
        threshold=0.01,
        n_rounds=10,
        false_expansions=0,
        missed_expansions=8,
        correct_expansions=1,
        correct_contractions=1,
    )
    greedy = CriterionMeasurement(
        name="b",
        threshold=0.5,
        n_rounds=10,
        false_expansions=3,
        missed_expansions=0,
        correct_expansions=6,
        correct_contractions=1,
    )

    assert safe.rank_key < greedy.rank_key
    assert min((safe, greedy), key=lambda m: m.rank_key) is safe


def test_module_never_weights_the_two_errors_into_one_number() -> None:
    """Статическая проверка: в коде нет сложения ложных и упущенных
    расширений в одну величину."""

    tree = ast.parse((ROOT / "convergence.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            dumped = ast.dump(node)
            assert not (
                "false_expansions" in dumped and "missed_expansions" in dumped
            ), "две ошибки свёрнуты в одну величину"


def test_rank_agreement_catches_what_deviation_misses() -> None:
    """Смысл замера: кандидаты §10.4 ошибаются на разных раундах, и какой
    ошибается реже — вопрос к данным, а не к вкусу."""

    reversed_but_close = _round(0, [(102.0, 100.0), (101.0, 101.0), (100.0, 102.0)])

    assert absolute_deviation_criterion(0.05)(reversed_but_close.checks) is True
    assert rank_agreement_criterion(0.5)(reversed_but_close.checks) is False


# --- 4. Порог просматривается сеткой ---------------------------------------


def test_every_threshold_of_the_grid_is_reported() -> None:
    """Единственное число «оптимальный порог 0.07» скрывает, устойчив он или
    стоит на игле."""

    rounds = [
        _round(0, [(101.0, 100.0), (201.0, 200.0)]),
        _round(1, [(150.0, 100.0), (250.0, 200.0)]),
    ]
    grid = (0.01, 0.05, 0.6)

    report = measure_criteria(
        rounds, regret_tolerance=0.05, deviation_thresholds=grid
    )
    sweep = report.sweep_of("absolute_deviation")

    assert tuple(m.threshold for m in sweep.measurements) == grid
    assert all(m.n_rounds == 2 for m in sweep.measurements)


def test_all_three_candidates_are_measured() -> None:
    rounds = [
        _round(0, [(101.0, 100.0), (201.0, 200.0)]),
        _round(1, [(300.0, 100.0), (100.0, 200.0)]),
    ]

    report = measure_criteria(rounds, regret_tolerance=0.05)

    assert {sweep.name for sweep in report.sweeps} == {
        "absolute_deviation",
        "rank_agreement",
        "both",
    }


def test_stability_of_the_best_threshold_is_reported() -> None:
    rounds = [
        _round(0, [(101.0, 100.0), (201.0, 200.0)]),
        _round(1, [(102.0, 100.0), (202.0, 200.0)]),
    ]

    report = measure_criteria(rounds, regret_tolerance=0.05)
    sweep = report.sweep_of("absolute_deviation")

    assert isinstance(sweep.stable, bool)
    assert sweep.best in sweep.measurements


# --- 5. Вердикт: замер, а не выбор -----------------------------------------


def test_verdict_names_a_winner_only_on_real_data() -> None:
    rounds = [
        _round(0, [(101.0, 100.0), (201.0, 200.0)]),
        _round(1, [(102.0, 100.0), (202.0, 200.0)]),
    ]

    report = measure_criteria(rounds, regret_tolerance=0.05)

    assert isinstance(report, CalibrationReport)
    assert report.winner is not None
    assert report.winner.name in {"absolute_deviation", "rank_agreement", "both"}
    assert "ложных расширений" in report.verdict


def test_synthetic_table_blocks_the_verdict() -> None:
    """Правило 4: критерий, откалиброванный на выдуманных данных, — это
    выбор, замаскированный под замер, ровно то, что карточка запрещает."""

    rounds = [
        _round(0, [(101.0, 100.0), (201.0, 200.0)]),
        _round(1, [(102.0, 100.0), (202.0, 200.0)]),
    ]

    report = measure_criteria(rounds, regret_tolerance=0.05, synthetic_inputs=True)

    assert report.winner is None
    assert "синтетическ" in report.verdict


def test_one_round_is_not_a_measurement() -> None:
    """На одном раунде кандидаты не различаются — объявлять победителя
    значило бы выбирать, а не мерить."""

    report = measure_criteria([_round(0, [(101.0, 100.0), (201.0, 200.0)])], regret_tolerance=0.05)

    assert report.winner is None
    assert "замер не состоялся" in report.verdict


def test_module_hardcodes_no_winner() -> None:
    """Главное требование карточки, проверенное структурно: в коде нет
    константы с «выбранным» критерием или его порогом."""

    text = (ROOT / "convergence.py").read_text(encoding="utf-8")
    lowered = text.lower()

    for forbidden in ("default_criterion", "chosen_criterion", "selected_criterion"):
        assert forbidden not in lowered


# --- Отказы вместо правдоподобных чисел ------------------------------------


def test_empty_history_is_rejected() -> None:
    with pytest.raises(ConvergenceError):
        measure_criteria([], regret_tolerance=0.05)


def test_empty_threshold_grid_is_rejected() -> None:
    with pytest.raises(ConvergenceError):
        measure_criteria(
            [_round(0, [(1.0, 1.0), (2.0, 2.0)])],
            regret_tolerance=0.05,
            deviation_thresholds=(),
        )


def test_negative_tolerance_is_rejected() -> None:
    with pytest.raises(ConvergenceError):
        absolute_deviation_criterion(-0.1)


def test_correlation_threshold_outside_the_range_is_rejected() -> None:
    with pytest.raises(ConvergenceError):
        rank_agreement_criterion(1.5)


def test_unknown_candidate_lookup_is_rejected() -> None:
    report = measure_criteria(
        [_round(0, [(1.0, 1.0), (2.0, 2.0)])], regret_tolerance=0.05
    )

    with pytest.raises(ConvergenceError):
        report.sweep_of("нет такого критерия")
