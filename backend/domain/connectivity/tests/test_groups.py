from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from backend.core.contracts import Groups, Lambda, Role

from backend.domain.connectivity.groups import (
    GroupingParams,
    build_groups,
    coverage_of,
    group_hash,
    group_sizes,
    lambda_hash,
    moved_share,
    validate_groups,
)

WINDOW_START = date(2007, 1, 1)
WINDOW_END = date(2010, 1, 1)


def lambda_of(
    producers: tuple[str, ...],
    injectors: tuple[str, ...],
    matrix: tuple[tuple[float, ...], ...],
) -> Lambda:
    return Lambda(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        producers=producers,
        injectors=injectors,
        matrix=matrix,
        lag_months=3,
        amplitude=0.2,
        stability=0.8,
        rank=len(injectors),
        condition_number=4.0,
        achievability_ok={well: True for well in injectors},
    )


def block_lambda(
    n_blocks: int,
    injectors_per_block: int,
    producers_per_block: int,
    inside: float = 1.0,
    outside: float = 0.0,
) -> Lambda:
    injectors = tuple(
        f"i{block}_{k}"
        for block in range(n_blocks)
        for k in range(injectors_per_block)
    )
    producers = tuple(
        f"p{block}_{k}"
        for block in range(n_blocks)
        for k in range(producers_per_block)
    )
    matrix = tuple(
        tuple(
            inside
            if row // producers_per_block == column // injectors_per_block
            else outside
            for column in range(len(injectors))
        )
        for row in range(len(producers))
    )
    return lambda_of(producers, injectors, matrix)


def test_three_planted_blocks_come_back_as_three_groups() -> None:
    influence = block_lambda(
        n_blocks=3, injectors_per_block=2, producers_per_block=4
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == 3
    assert report.n_injectors == 6
    assert report.n_producers == 12
    assert report.coverage == report.n_wells == 18
    assert sorted(group_sizes(artifact).values()) == [6, 6, 6]


def test_each_planted_block_lands_in_one_group_together() -> None:
    influence = block_lambda(
        n_blocks=3, injectors_per_block=2, producers_per_block=4
    )
    artifact, _ = build_groups(influence)
    for block in range(3):
        members = {f"i{block}_{k}" for k in range(2)} | {
            f"p{block}_{k}" for k in range(4)
        }
        assert any(
            members <= set(group) for group in artifact.groups.values()
        ), f"блок {block} разрезан между участками"


def test_number_of_groups_follows_the_data_not_a_literal() -> None:
    sizes = {}
    for n_blocks in (2, 3, 5, 7):
        influence = block_lambda(
            n_blocks=n_blocks, injectors_per_block=2, producers_per_block=3
        )
        _, report = build_groups(influence)
        sizes[n_blocks] = report.n_groups
    assert sizes == {2: 2, 3: 3, 5: 5, 7: 7}


def test_two_injectors_on_the_same_rock_end_up_in_one_group() -> None:
    influence = lambda_of(
        producers=("p1", "p2"),
        injectors=("i1", "i2"),
        matrix=((1.0, 1.0), (1.0, 1.0)),
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == 1
    assert report.merged_injector_pairs == (("i1", "i2"),)
    assert set(next(iter(artifact.groups.values()))) == {"p1", "p2", "i1", "i2"}


def test_two_injectors_on_different_rock_stay_apart() -> None:
    influence = lambda_of(
        producers=("p1", "p2"),
        injectors=("i1", "i2"),
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == 2
    assert report.merged_injector_pairs == ()
    assert coverage_of(artifact) == 4


def test_a_producer_fed_by_two_sections_belongs_to_both() -> None:
    influence = lambda_of(
        producers=("p_left", "p_right", "p_shared"),
        injectors=("i_left", "i_right"),
        matrix=((1.0, 0.0), (0.0, 1.0), (0.5, 0.5)),
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == 2
    assert report.overlapped_wells == ("p_shared",)
    holding = [
        group_id
        for group_id, members in artifact.groups.items()
        if "p_shared" in members
    ]
    assert len(holding) == 2


def test_a_marginal_producer_does_not_leak_into_the_second_section() -> None:
    influence = lambda_of(
        producers=("p_left", "p_right", "p_leaning"),
        injectors=("i_left", "i_right"),
        matrix=((1.0, 0.0), (0.0, 1.0), (1.0, 0.01)),
    )
    artifact, report = build_groups(influence)
    assert report.overlapped_wells == ()
    holding = [
        group_id
        for group_id, members in artifact.groups.items()
        if "p_leaning" in members
    ]
    assert len(holding) == 1


def test_membership_threshold_controls_the_overlaps() -> None:
    influence = lambda_of(
        producers=("p_left", "p_right", "p_shared"),
        injectors=("i_left", "i_right"),
        matrix=((1.0, 0.0), (0.0, 1.0), (0.7, 0.3)),
    )
    _, wide = build_groups(
        influence, GroupingParams(membership_share=0.2)
    )
    _, narrow = build_groups(
        influence, GroupingParams(membership_share=0.4)
    )
    assert wide.overlapped_wells == ("p_shared",)
    assert narrow.overlapped_wells == ()


def test_every_group_holds_at_least_one_injector() -> None:
    influence = block_lambda(
        n_blocks=4, injectors_per_block=1, producers_per_block=5
    )
    artifact, _ = build_groups(influence)
    injectors = set(influence.injectors)
    for group_id, members in artifact.groups.items():
        assert set(members) & injectors, group_id


def test_full_fund_coverage_is_taken_from_the_data() -> None:
    influence = block_lambda(
        n_blocks=6, injectors_per_block=3, producers_per_block=14
    )
    artifact, report = build_groups(influence)
    expected = len(set(influence.producers) | set(influence.injectors))
    assert report.n_wells == expected
    assert report.coverage == expected
    assert coverage_of(artifact) == expected


def test_every_well_of_the_real_deck_lands_in_a_group(deck) -> None:
    fund = tuple(sorted(deck.wells))
    injectors = tuple(
        sorted({record.well for record in deck.records if record.role is Role.INJ})
    )
    producers = tuple(
        sorted({record.well for record in deck.records if record.role is Role.PROD})
    )
    matrix = tuple(
        tuple(
            1.0 if producers.index(producer) % len(injectors) == column else 0.0
            for column in range(len(injectors))
        )
        for producer in producers
    )
    influence = lambda_of(producers, injectors, matrix)
    artifact, report = build_groups(influence, extra_wells=fund)
    assert report.n_wells == len(fund)
    assert report.coverage == report.n_wells
    assert coverage_of(artifact) == len(fund)
    for group_id, members in artifact.groups.items():
        assert set(members) & set(injectors), group_id


def test_coverage_counts_wells_outside_lambda_too() -> None:
    influence = block_lambda(
        n_blocks=6, injectors_per_block=3, producers_per_block=14
    )
    extra = ("p_shut_in",)
    artifact, report = build_groups(influence, extra_wells=extra)
    expected = len(
        set(influence.producers) | set(influence.injectors) | set(extra)
    )
    assert report.coverage == expected
    assert report.n_wells == expected
    assert coverage_of(artifact) == expected
    assert report.degenerate is True


def test_the_same_lambda_and_seed_give_the_same_hash() -> None:
    influence = block_lambda(
        n_blocks=3, injectors_per_block=2, producers_per_block=4
    )
    first, _ = build_groups(influence, GroupingParams(seed=7))
    second, _ = build_groups(influence, GroupingParams(seed=7))
    assert first.groups == second.groups
    assert first.group_hash == second.group_hash
    assert first.lambda_hash == second.lambda_hash


def test_a_different_seed_is_a_different_artifact() -> None:
    influence = block_lambda(
        n_blocks=3, injectors_per_block=2, producers_per_block=4
    )
    first, _ = build_groups(influence, GroupingParams(seed=7))
    second, _ = build_groups(influence, GroupingParams(seed=8))
    assert first.groups == second.groups
    assert first.group_hash != second.group_hash


def test_a_different_lambda_is_a_different_hash() -> None:
    left = block_lambda(n_blocks=3, injectors_per_block=2, producers_per_block=4)
    right = block_lambda(n_blocks=4, injectors_per_block=2, producers_per_block=4)
    first, _ = build_groups(left)
    second, _ = build_groups(right)
    assert first.lambda_hash != second.lambda_hash
    assert first.group_hash != second.group_hash


def test_the_order_of_the_axes_does_not_change_the_grouping() -> None:
    influence = lambda_of(
        producers=("p1", "p2"),
        injectors=("i1", "i2"),
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    flipped = lambda_of(
        producers=("p2", "p1"),
        injectors=("i2", "i1"),
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    first, _ = build_groups(influence)
    second, _ = build_groups(flipped)
    assert sorted(
        tuple(sorted(members)) for members in first.groups.values()
    ) == sorted(tuple(sorted(members)) for members in second.groups.values())


def test_a_zero_lambda_gives_one_group_per_injector_and_says_so() -> None:
    influence = lambda_of(
        producers=("p1", "p2", "p3"),
        injectors=("i1", "i2"),
        matrix=((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == len(influence.injectors)
    assert report.isolated_producers == ("p1", "p2", "p3")
    assert report.degenerate is True
    assert report.coverage == 5
    validate_groups(artifact, influence, ("p1", "p2", "p3", "i1", "i2"))


def test_a_single_injector_fund_gives_a_single_group() -> None:
    influence = lambda_of(
        producers=(), injectors=("i1",), matrix=()
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == 1
    assert report.coverage == 1
    assert next(iter(artifact.groups.values())) == ("i1",)


def test_a_single_pair_fund_gives_a_single_group() -> None:
    influence = lambda_of(
        producers=("p1",), injectors=("i1",), matrix=((1.0,),)
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == 1
    assert set(next(iter(artifact.groups.values()))) == {"p1", "i1"}


def test_a_fund_without_injectors_is_refused_not_guessed() -> None:
    influence = lambda_of(
        producers=("p1", "p2"), injectors=(), matrix=((), ())
    )
    with pytest.raises(ValueError, match="ни одной нагнетательной"):
        build_groups(influence)


def test_an_empty_fund_is_refused() -> None:
    influence = lambda_of(producers=(), injectors=(), matrix=())
    with pytest.raises(ValueError, match="фонд пуст"):
        build_groups(influence)


def test_a_disconnected_producer_is_named_and_still_covered() -> None:
    influence = lambda_of(
        producers=("p_linked", "p_orphan"),
        injectors=("i1",),
        matrix=((1.0,), (0.0,)),
    )
    artifact, report = build_groups(influence)
    assert report.isolated_producers == ("p_orphan",)
    assert report.degenerate is True
    assert coverage_of(artifact) == 3


def test_negative_sensitivities_do_not_create_a_connection() -> None:
    influence = lambda_of(
        producers=("p1", "p2"),
        injectors=("i1", "i2"),
        matrix=((1.0, -1.0), (-1.0, 1.0)),
    )
    artifact, report = build_groups(influence)
    assert report.n_groups == 2
    assert report.overlapped_wells == ()
    assert coverage_of(artifact) == 4


def test_a_well_that_was_both_producer_and_injector_is_reported() -> None:
    influence = lambda_of(
        producers=("p1", "w_converted"),
        injectors=("i1", "w_converted"),
        matrix=((1.0, 0.2), (0.0, 1.0)),
    )
    artifact, report = build_groups(influence)
    assert report.dual_role_wells == ("w_converted",)
    holding = [
        group_id
        for group_id, members in artifact.groups.items()
        if "w_converted" in members
    ]
    assert holding
    assert coverage_of(artifact) == 3


def test_a_dual_role_well_carries_its_injector_identity() -> None:
    influence = lambda_of(
        producers=("p1", "w_converted"),
        injectors=("i1", "w_converted"),
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    artifact, _ = build_groups(influence)
    for members in artifact.groups.values():
        if "w_converted" not in members:
            continue
        assert "w_converted" in members
    injector_group = [
        group_id
        for group_id, members in artifact.groups.items()
        if "w_converted" in members
    ]
    assert len(injector_group) >= 1


def test_the_merge_threshold_is_refused_outside_its_range() -> None:
    with pytest.raises(ValueError, match="порог слияния"):
        GroupingParams(merge_overlap=0.0)
    with pytest.raises(ValueError, match="порог слияния"):
        GroupingParams(merge_overlap=1.5)
    with pytest.raises(ValueError, match="порог принадлежности"):
        GroupingParams(membership_share=0.0)


def test_a_lower_merge_threshold_never_gives_more_groups() -> None:
    influence = lambda_of(
        producers=("p1", "p2", "p3"),
        injectors=("i1", "i2", "i3"),
        matrix=(
            (1.0, 0.6, 0.0),
            (0.6, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
    )
    counts = []
    for threshold in (0.2, 0.5, 0.9):
        _, report = build_groups(
            influence, GroupingParams(merge_overlap=threshold)
        )
        counts.append(report.n_groups)
    assert counts == sorted(counts)


def test_validate_catches_a_group_without_an_injector() -> None:
    influence = lambda_of(
        producers=("p1",), injectors=("i1",), matrix=((1.0,),)
    )
    broken = Groups(
        groups={"G1": ("i1",), "G2": ("p1",)},
        lambda_hash=lambda_hash(influence),
        group_hash="0" * 64,
    )
    with pytest.raises(ValueError, match="без нагнетательной"):
        validate_groups(broken, influence, ("p1", "i1"))


def test_validate_catches_an_uncovered_well() -> None:
    influence = lambda_of(
        producers=("p1", "p2"), injectors=("i1",), matrix=((1.0,), (1.0,))
    )
    broken = Groups(
        groups={"G1": ("i1", "p1")},
        lambda_hash=lambda_hash(influence),
        group_hash="0" * 64,
    )
    with pytest.raises(ValueError, match="вне участков"):
        validate_groups(broken, influence, ("p1", "p2", "i1"))


def test_validate_catches_an_empty_group() -> None:
    influence = lambda_of(
        producers=("p1",), injectors=("i1",), matrix=((1.0,),)
    )
    broken = Groups(
        groups={"G1": ("i1", "p1"), "G2": ()},
        lambda_hash=lambda_hash(influence),
        group_hash="0" * 64,
    )
    with pytest.raises(ValueError, match="пуст"):
        validate_groups(broken, influence, ("p1", "i1"))


def test_a_stable_second_batch_moves_nobody() -> None:
    influence = block_lambda(
        n_blocks=3, injectors_per_block=2, producers_per_block=4
    )
    first, _ = build_groups(influence)
    second, _ = build_groups(influence)
    assert moved_share(first, second) == 0.0


def test_a_second_batch_that_regroups_the_fund_is_measured() -> None:
    left = block_lambda(
        n_blocks=3, injectors_per_block=2, producers_per_block=4
    )
    right = replace(
        left,
        matrix=tuple(
            tuple(1.0 for _ in row) for row in left.matrix
        ),
    )
    first, _ = build_groups(left)
    second, _ = build_groups(right)
    assert moved_share(first, second) > 0.0
    assert moved_share(first, second) <= 1.0


def test_lambda_hash_ignores_fields_that_do_not_shape_the_grouping() -> None:
    influence = block_lambda(
        n_blocks=2, injectors_per_block=1, producers_per_block=2
    )
    relaxed = replace(influence, stability=0.1, condition_number=99.0)
    assert lambda_hash(influence) == lambda_hash(relaxed)


def test_group_hash_moves_when_the_parameters_move() -> None:
    influence = block_lambda(
        n_blocks=2, injectors_per_block=1, producers_per_block=2
    )
    artifact, _ = build_groups(influence)
    other = group_hash(
        artifact.groups, influence, GroupingParams(merge_overlap=0.9)
    )
    assert artifact.group_hash != other


def test_the_artifact_hashes_are_sha256_hex() -> None:
    influence = block_lambda(
        n_blocks=2, injectors_per_block=1, producers_per_block=2
    )
    artifact, _ = build_groups(influence)
    assert len(artifact.group_hash) == 64
    assert len(artifact.lambda_hash) == 64
    assert set(artifact.group_hash) <= set("0123456789abcdef")
