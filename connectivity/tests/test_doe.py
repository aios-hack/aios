from __future__ import annotations

from datetime import date

import pytest

from contracts import Role

from connectivity import (
    Amplitude,
    DeckSchedule,
    DoEPlan,
    FundHistory,
    Level,
    Window,
    achievability,
    active_fund_in_window,
    amplitude_from_prior,
    hadamard,
    is_hadamard,
    normalized,
    orthogonality_of,
    plackett_burman,
    plan_runs,
    plans_for_windows,
    realized_matrix,
    setpoint_changes,
    slice_windows,
)
from connectivity.fund import ActiveFund

SEED = 7
COVERAGE = 0.8
WINDOW_BOUNDARIES: tuple[date, ...] = (
    date(2007, 1, 1),
    date(2010, 1, 1),
    date(2013, 1, 1),
    date(2017, 1, 1),
    date(2022, 1, 1),
    date(2026, 1, 1),
)


def amplitude(deck: DeckSchedule) -> Amplitude:
    distribution = setpoint_changes(
        deck, Role.INJ, deck.date_index(WINDOW_BOUNDARIES[0])
    )
    return amplitude_from_prior(distribution, COVERAGE)


def fund_of(count: int) -> ActiveFund:
    return ActiveFund(
        when=WINDOW_BOUNDARIES[0],
        deck_date_index=0,
        injectors=tuple(f"I{i:03d}" for i in range(count)),
        producers=("P001",),
        commissioned=tuple(f"I{i:03d}" for i in range(count)) + ("P001",),
    )


def a_window() -> Window:
    return Window(start=WINDOW_BOUNDARIES[0], end=WINDOW_BOUNDARIES[1])


def a_plan(count: int, amp: Amplitude) -> DoEPlan:
    return plackett_burman(a_window(), fund_of(count), amp, seed=SEED)


def test_plan_width_is_the_active_fund_of_the_window_not_the_number_41(
    deck: DeckSchedule, history: FundHistory
) -> None:
    amp = amplitude(deck)
    widths = []
    for window, fund in slice_windows(deck, WINDOW_BOUNDARIES, history):
        plan = plackett_burman(window, fund, amp, seed=SEED)
        assert plan.plan_width == fund.plan_width
        widths.append(plan.plan_width)
    assert widths[0] < widths[-1]
    assert len(set(widths)) > 1


def test_first_window_is_narrower_than_the_last(
    deck: DeckSchedule, history: FundHistory
) -> None:
    amp = amplitude(deck)
    first = plackett_burman(
        Window(WINDOW_BOUNDARIES[0], WINDOW_BOUNDARIES[1]),
        active_fund_in_window(
            deck, Window(WINDOW_BOUNDARIES[0], WINDOW_BOUNDARIES[1]), history
        ),
        amp,
        seed=SEED,
    )
    last = plackett_burman(
        Window(WINDOW_BOUNDARIES[-2], WINDOW_BOUNDARIES[-1]),
        active_fund_in_window(
            deck, Window(WINDOW_BOUNDARIES[-2], WINDOW_BOUNDARIES[-1]), history
        ),
        amp,
        seed=SEED,
    )
    assert first.plan_width < last.plan_width
    assert first.n_runs < last.n_runs


def test_number_of_runs_is_of_the_order_of_the_number_of_wells(
    deck: DeckSchedule, history: FundHistory
) -> None:
    amp = amplitude(deck)
    for window, fund in slice_windows(deck, WINDOW_BOUNDARIES, history):
        plan = plackett_burman(window, fund, amp, seed=SEED)
        assert plan.plan_width <= plan.n_runs
        assert plan.n_runs < 2 * plan.plan_width


def test_half_of_the_fund_goes_high_and_half_goes_low_per_column(
    deck: DeckSchedule, history: FundHistory
) -> None:
    amp = amplitude(deck)
    for window, fund in slice_windows(deck, WINDOW_BOUNDARIES, history):
        plan = plackett_burman(window, fund, amp, seed=SEED)
        assert plan.column_balanced()
        for high, low in plan.column_balance().values():
            assert high + low == plan.n_runs


def test_half_high_half_low_per_run_when_the_design_needs_no_padding(
    deck: DeckSchedule,
) -> None:
    amp = amplitude(deck)
    plan = a_plan(plan_runs(27) - 1, amp)
    assert plan.padding_columns == 0
    assert plan.row_balanced()
    for high, low in (row.balance() for row in plan.rows):
        assert abs(high - low) <= 1


def test_design_is_orthogonal_by_construction(deck: DeckSchedule) -> None:
    """Обусловленность плана — не 1.0 (исправлено 16.08).

    Столбец-константа матрицы Адамара в план не входит, поэтому недиагональ
    матрицы Грама равна −1, а не нулю: Gram = `(n_runs + 1)·I − J`. Спектр —
    `n_runs + 1` кратности `width − 1` и `n_runs + 1 − width` на собственном
    векторе из единиц, то есть обусловленность
    `(n_runs + 1) / (n_runs + 1 − width)`: 28 на квадратном плане в 27
    прогонов и тем ближе к единице, чем больше в плане пустых колонок
    (28 при width=27, 10.67 при width=29 и 31 прогоне).

    Прежнее ожидание 1.0 закрепляло артефакт степенного метода, который
    стартовал ровно с вектора `[1…1]` — тот попадал в собственный вектор
    наименьшего значения, и «наибольшее» находилось равным ему. Полная
    ортогональность плана по замыслу предъявляется корреляцией колонок
    (`1 / n_runs`) и полным рангом, а не единичной обусловленностью.
    """

    amp = amplitude(deck)
    for count in (27, 29, 38, 39, 41):
        plan = a_plan(count, amp)
        diagnosis = orthogonality_of(plan.design_matrix())
        assert diagnosis.rank == plan.plan_width
        expected = (plan.n_runs + 1) / (plan.n_runs + 1 - plan.plan_width)
        assert diagnosis.condition_number == pytest.approx(expected)
        assert diagnosis.max_abs_correlation == pytest.approx(1.0 / plan.n_runs)


def test_run_count_is_the_next_multiple_of_four_above_the_fund() -> None:
    assert plan_runs(27) == 28
    assert plan_runs(29) == 32
    assert plan_runs(41) == 44
    assert plan_runs(1) == 4


def test_plan_on_an_empty_fund_is_refused() -> None:
    empty = ActiveFund(
        when=WINDOW_BOUNDARIES[0],
        deck_date_index=0,
        injectors=(),
        producers=("P001",),
        commissioned=("P001",),
    )
    with pytest.raises(ValueError, match="активных нагнетательных нет"):
        plackett_burman(a_window(), empty, Amplitude(30.0, 5.0, 25.0), seed=SEED)


def test_amplitude_comes_from_the_deck_prior_not_from_a_guess(
    deck: DeckSchedule,
) -> None:
    amp = amplitude(deck)
    assert amp.step_low_m3_per_day >= 5.0
    assert amp.step_high_m3_per_day <= 25.0
    assert amp.base_level_m3_per_day == pytest.approx(30.0)
    assert 0.15 < amp.relative_low < 0.2
    assert 0.4 < amp.relative_high < 0.9


def test_targets_move_up_and_down_from_the_actual_level(
    deck: DeckSchedule,
) -> None:
    amp = amplitude(deck)
    plan = a_plan(27, amp)
    current = {well: 40.0 for well in plan.injectors}
    targets = plan.targets(0, current)
    row = plan.rows[0]
    for well, target in targets.items():
        if row.levels[well] is Level.HIGH:
            assert target > current[well]
        else:
            assert target < current[well]


def test_targets_require_the_actual_level_of_every_well(
    deck: DeckSchedule,
) -> None:
    plan = a_plan(27, amplitude(deck))
    with pytest.raises(ValueError, match="текущего уровня"):
        plan.targets(0, {plan.injectors[0]: 40.0})


def test_shortfall_at_the_pressure_limit_is_diagnosed_not_hidden(
    deck: DeckSchedule,
) -> None:
    amp = amplitude(deck)
    plan = a_plan(27, amp)
    current = {well: 40.0 for well in plan.injectors}
    capped = plan.injectors[:9]
    targets = []
    actuals = []
    for run_index in range(plan.n_runs):
        target = plan.targets(run_index, current)
        targets.append(target)
        actuals.append(
            {
                well: (
                    min(value, current[well]) if well in capped else value
                )
                for well, value in target.items()
            }
        )
    report = achievability(plan, targets, actuals, tolerance=0.0)
    failing = {check.well for check in report.shortfalls()}
    assert failing
    assert failing <= set(capped)
    ok = report.achievability_ok()
    assert all(not ok[well] for well in failing)
    assert all(ok[well] for well in plan.injectors if well not in failing)


def test_orthogonality_breaks_on_realized_rates_and_is_measured(
    deck: DeckSchedule,
) -> None:
    amp = amplitude(deck)
    plan = a_plan(27, amp)
    current = {well: 40.0 for well in plan.injectors}
    frozen = plan.injectors[:4]
    actuals = []
    for run_index in range(plan.n_runs):
        target = plan.targets(run_index, current)
        actuals.append(
            {
                well: (current[well] if well in frozen else value)
                for well, value in target.items()
            }
        )
    realized = realized_matrix(plan, actuals, current)
    diagnosis = orthogonality_of(realized)
    designed = orthogonality_of(plan.design_matrix())
    assert designed.rank == plan.plan_width
    assert diagnosis.rank < designed.rank
    assert diagnosis.condition_number == float("inf")


def test_systematic_shortfall_lowers_the_amplitude_of_the_whole_plan(
    deck: DeckSchedule,
) -> None:
    amp = amplitude(deck)
    plan = a_plan(27, amp)
    current = {well: 40.0 for well in plan.injectors}
    targets = [plan.targets(i, current) for i in range(plan.n_runs)]
    actuals = [
        {well: min(value, current[well]) for well, value in target.items()}
        for target in targets
    ]
    report = achievability(plan, targets, actuals, tolerance=0.0)
    assert report.systematic_shortfall()
    lowered = report.suggested_amplitude(amp)
    assert lowered.step_high_m3_per_day < amp.step_high_m3_per_day


def test_amplitude_is_untouched_when_the_plan_is_achieved(
    deck: DeckSchedule,
) -> None:
    amp = amplitude(deck)
    plan = a_plan(27, amp)
    current = {well: 40.0 for well in plan.injectors}
    targets = [plan.targets(i, current) for i in range(plan.n_runs)]
    report = achievability(plan, targets, targets, tolerance=0.0)
    assert not report.systematic_shortfall()
    assert report.suggested_amplitude(amp) == amp


def test_achievability_refuses_a_partial_check(deck: DeckSchedule) -> None:
    plan = a_plan(27, amplitude(deck))
    current = {well: 40.0 for well in plan.injectors}
    targets = [plan.targets(i, current) for i in range(plan.n_runs)]
    with pytest.raises(ValueError, match="прогонов"):
        achievability(plan, targets[:-1], targets[:-1], tolerance=0.0)


def test_plan_is_deterministic_for_the_same_seed(deck: DeckSchedule) -> None:
    amp = amplitude(deck)
    first = a_plan(27, amp)
    second = a_plan(27, amp)
    assert first.design_matrix() == second.design_matrix()


def test_seed_changes_which_well_takes_which_column(deck: DeckSchedule) -> None:
    amp = amplitude(deck)
    first = plackett_burman(a_window(), fund_of(27), amp, seed=1)
    second = plackett_burman(a_window(), fund_of(27), amp, seed=2)
    assert first.injectors == second.injectors
    assert first.design_matrix() != second.design_matrix()


def test_plans_for_windows_gives_one_plan_per_window(
    deck: DeckSchedule, history: FundHistory
) -> None:
    sliced = slice_windows(deck, WINDOW_BOUNDARIES, history)
    plans = plans_for_windows(sliced, amplitude(deck), seed=SEED)
    assert len(plans) == len(sliced)
    for plan, (window, fund) in zip(plans, sliced):
        assert plan.window == window
        assert plan.injectors == tuple(sorted(fund.injectors))


def test_hadamard_matrices_are_orthogonal_for_every_needed_order() -> None:
    for order in (4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44):
        matrix = hadamard(order)
        assert is_hadamard(matrix)
        assert is_hadamard(normalized(matrix))


def test_hadamard_of_a_non_multiple_of_four_is_refused() -> None:
    with pytest.raises(ValueError, match="кратен четырём"):
        hadamard(6)
