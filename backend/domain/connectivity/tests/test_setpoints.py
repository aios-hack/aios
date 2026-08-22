from __future__ import annotations

import pytest

from backend.core.contracts import Role, T0

from backend.domain.connectivity import DeckSchedule, setpoint_changes

COVERAGE = 0.95


@pytest.fixture(scope="session")
def injection(deck: DeckSchedule):
    return setpoint_changes(deck, Role.INJ, deck.date_index(T0))


@pytest.fixture(scope="session")
def production(deck: DeckSchedule):
    return setpoint_changes(deck, Role.PROD, deck.date_index(T0))


def test_injection_steps_run_5_to_25(injection) -> None:
    low, high = injection.dominant_step_range(COVERAGE)
    assert (low, high) == (5.0, 25.0)


def test_injection_median_level_is_30(injection) -> None:
    assert injection.median_level_m3_per_day == 30.0


def test_amplitude_prior_is_17_to_83_percent(injection) -> None:
    low, high = injection.amplitude_prior(COVERAGE)
    assert low == pytest.approx(5.0 / 30.0, abs=5e-3)
    assert high == pytest.approx(25.0 / 30.0, abs=5e-3)
    assert round(low * 100) == 17
    assert round(high * 100) == 83


def test_steps_are_multiples_of_five(injection) -> None:
    for step in injection.step_histogram():
        assert step % 5.0 == 0.0


def test_dominant_range_covers_declared_share(injection) -> None:
    histogram = injection.step_histogram()
    total = sum(histogram.values())
    low, high = injection.dominant_step_range(COVERAGE)
    inside = sum(count for step, count in histogram.items() if low <= step <= high)
    assert inside / total >= COVERAGE


def test_full_coverage_exposes_outliers_beyond_the_card_range(injection) -> None:
    low, high = injection.dominant_step_range(1.0)
    assert low == 5.0
    assert high > 25.0
    histogram = injection.step_histogram()
    outliers = sum(count for step, count in histogram.items() if step > 25.0)
    assert outliers == 3


def test_injection_change_share_counts_the_t0_boundary(
    injection, deck: DeckSchedule
) -> None:
    assert len(injection.changes) == 122
    assert injection.change_share == pytest.approx(0.0149, abs=5e-4)


def test_dropping_the_boundary_reproduces_the_card_1_32_percent(
    deck: DeckSchedule,
) -> None:
    without_boundary = setpoint_changes(
        deck, Role.INJ, deck.date_index(T0), carry_level_across_boundary=False
    )
    assert len(without_boundary.changes) == 108
    assert without_boundary.change_share == pytest.approx(0.0132, abs=5e-4)


def test_boundary_changes_are_real_moves_on_t0(injection, deck: DeckSchedule) -> None:
    t0_index = deck.date_index(T0)
    at_boundary = [c for c in injection.changes if c.deck_date_index == t0_index]
    assert len(at_boundary) == 14
    for change in at_boundary:
        assert change.current_m3_per_day < change.previous_m3_per_day


def test_boundary_does_not_move_the_amplitude_prior(deck: DeckSchedule) -> None:
    with_boundary = setpoint_changes(deck, Role.INJ, deck.date_index(T0))
    without_boundary = setpoint_changes(
        deck, Role.INJ, deck.date_index(T0), carry_level_across_boundary=False
    )
    assert with_boundary.dominant_step_range(
        COVERAGE
    ) == without_boundary.dominant_step_range(COVERAGE)
    assert (
        with_boundary.median_level_m3_per_day
        == without_boundary.median_level_m3_per_day
    )


def test_producers_move_less_often_than_injectors(injection, production) -> None:
    assert production.change_share < injection.change_share


def test_producer_steps_are_also_five_grained(production) -> None:
    for step in production.step_histogram():
        assert step % 5.0 == 0.0


def test_relative_steps_are_bounded_below_by_grid(injection) -> None:
    relatives = injection.relative_steps()
    assert relatives
    assert min(relatives) > 0.0
    assert injection.quantile(relatives, 0.5) <= max(injection.amplitude_prior(COVERAGE))


def test_every_change_is_a_real_move(injection) -> None:
    for change in injection.changes:
        assert change.previous_m3_per_day != change.current_m3_per_day
        assert change.absolute_step_m3_per_day > 0.0


def test_changes_stay_inside_the_control_window(injection, deck: DeckSchedule) -> None:
    t0_index = deck.date_index(T0)
    for change in injection.changes:
        assert change.deck_date_index >= t0_index
        assert change.when >= T0


def test_first_appearance_is_not_a_change(deck: DeckSchedule) -> None:
    from_index = deck.date_index(T0)
    distribution = setpoint_changes(deck, Role.INJ, from_index)
    first_seen: dict[str, int] = {}
    for record in sorted(deck.records, key=lambda r: r.deck_date_index):
        if record.role is Role.INJ:
            first_seen.setdefault(record.well, record.deck_date_index)
    for change in distribution.changes:
        assert change.deck_date_index > first_seen[change.well]


def test_relative_step_from_zero_level_is_rejected(injection) -> None:
    from backend.domain.connectivity import SetpointChange

    change = SetpointChange(
        deck_date_index=injection.changes[0].deck_date_index,
        when=injection.changes[0].when,
        well="test",
        role=Role.INJ,
        previous_m3_per_day=0.0,
        current_m3_per_day=30.0,
    )
    with pytest.raises(ValueError, match="не определён от нулевого уровня"):
        change.relative_step


def test_role_without_setpoints_is_rejected(deck: DeckSchedule) -> None:
    with pytest.raises(ValueError, match="не несёт уставок"):
        setpoint_changes(deck, Role.NONE, 0)


def test_index_outside_deck_is_rejected(deck: DeckSchedule) -> None:
    with pytest.raises(ValueError, match="вне 0…"):
        setpoint_changes(deck, Role.INJ, len(deck.dates))


def test_coverage_outside_unit_interval_is_rejected(injection) -> None:
    with pytest.raises(ValueError, match="вне 0…1"):
        injection.dominant_step_range(1.5)
    with pytest.raises(ValueError, match="вне 0…1"):
        injection.dominant_step_range(0.0)
