from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from aios_backend.core.contracts import Groups, Lambda, Role

from aios_backend.domain.connectivity.groups import GroupingParams, build_groups, lambda_hash
from aios_backend.domain.connectivity.groups_artifact import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    ARTIFACT_FORMAT,
    GroupsArtifact,
    GroupsArtifactError,
    GroupsProvenance,
    GroupsProvenanceError,
    artifact_hash,
    build_artifact,
    cache_key,
    dumps,
    from_payload,
    is_current,
    load,
    loads,
    matches_params,
    normalized_payload,
    provenance_of,
    rehash,
    require_current,
    require_params,
    reusable_for,
    save,
    to_payload,
    verify_against_lambda,
)

WINDOW_START = date(2007, 1, 1)
WINDOW_END = date(2010, 1, 1)
LATER_START = date(2010, 1, 1)
LATER_END = date(2013, 1, 1)


def lambda_of(
    producers: tuple[str, ...],
    injectors: tuple[str, ...],
    matrix: tuple[tuple[float, ...], ...],
    window_start: date = WINDOW_START,
    window_end: date = WINDOW_END,
) -> Lambda:
    return Lambda(
        window_start=window_start,
        window_end=window_end,
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
    window_start: date = WINDOW_START,
    window_end: date = WINDOW_END,
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
            1.0
            if row // producers_per_block == column // injectors_per_block
            else 0.0
            for column in range(len(injectors))
        )
        for row in range(len(producers))
    )
    return lambda_of(producers, injectors, matrix, window_start, window_end)


@pytest.fixture
def influence() -> Lambda:
    return block_lambda(n_blocks=3, injectors_per_block=2, producers_per_block=4)


@pytest.fixture
def artifact(influence: Lambda) -> GroupsArtifact:
    built, _ = build_artifact(influence)
    return built


def test_the_artifact_carries_groups_both_hashes_window_seed_and_version(
    influence: Lambda, artifact: GroupsArtifact
) -> None:
    assert artifact.groups.groups
    assert artifact.group_hash == artifact.groups.group_hash
    assert artifact.lambda_hash == lambda_hash(influence)
    assert artifact.window == (influence.window_start, influence.window_end)
    assert artifact.provenance.seed == GroupingParams().seed
    assert artifact.provenance.algorithm == ALGORITHM_NAME
    assert artifact.provenance.algorithm_version == ALGORITHM_VERSION
    assert artifact.provenance.merge_overlap == GroupingParams().merge_overlap
    assert artifact.provenance.membership_share == GroupingParams().membership_share


def test_a_saved_artifact_comes_back_equal(artifact: GroupsArtifact) -> None:
    restored = loads(dumps(artifact))
    assert restored == artifact
    assert restored.groups == artifact.groups
    assert restored.provenance == artifact.provenance
    assert restored.fund == artifact.fund


def test_the_round_trip_survives_a_file(
    artifact: GroupsArtifact, tmp_path: Path
) -> None:
    path = tmp_path / "groups.json"
    save(artifact, path)
    assert load(path) == artifact


def test_a_missing_file_is_named_not_guessed(tmp_path: Path) -> None:
    with pytest.raises(GroupsArtifactError, match="не найден"):
        load(tmp_path / "нет.json")


def test_broken_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "groups.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(GroupsArtifactError, match="не разбирается как JSON"):
        load(path)


def test_the_hash_does_not_depend_on_the_order_of_serialization(
    artifact: GroupsArtifact,
) -> None:
    payload = to_payload(artifact)
    shuffled = {key: payload[key] for key in reversed(list(payload))}
    for group_id in shuffled["groups"]:
        shuffled["groups"][group_id] = list(reversed(shuffled["groups"][group_id]))
    shuffled["groups"] = {
        group_id: shuffled["groups"][group_id]
        for group_id in reversed(list(shuffled["groups"]))
    }
    shuffled["fund"] = list(reversed(shuffled["fund"]))
    restored = from_payload(shuffled)
    assert artifact_hash(restored) == artifact_hash(artifact)
    assert restored == artifact


def test_the_hash_is_stable_across_repeated_builds(influence: Lambda) -> None:
    first, _ = build_artifact(influence)
    second, _ = build_artifact(influence)
    assert artifact_hash(first) == artifact_hash(second)
    assert first.group_hash == second.group_hash


def test_the_hash_is_sha256_hex(artifact: GroupsArtifact) -> None:
    value = artifact_hash(artifact)
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def test_different_groups_give_different_hashes() -> None:
    left = block_lambda(n_blocks=3, injectors_per_block=2, producers_per_block=4)
    right = block_lambda(n_blocks=4, injectors_per_block=2, producers_per_block=4)
    first, _ = build_artifact(left)
    second, _ = build_artifact(right)
    assert first.groups.groups != second.groups.groups
    assert artifact_hash(first) != artifact_hash(second)


def test_the_same_groups_in_another_window_are_another_artifact() -> None:
    early = block_lambda(
        n_blocks=3,
        injectors_per_block=2,
        producers_per_block=4,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    late = block_lambda(
        n_blocks=3,
        injectors_per_block=2,
        producers_per_block=4,
        window_start=LATER_START,
        window_end=LATER_END,
    )
    first, _ = build_artifact(early)
    second, _ = build_artifact(late)
    assert first.groups.groups == second.groups.groups
    assert first.window != second.window
    assert artifact_hash(first) != artifact_hash(second)


def test_renaming_a_group_changes_the_hash(artifact: GroupsArtifact) -> None:
    members = dict(artifact.groups.groups)
    first_id = sorted(members)[0]
    renamed = {
        ("Z" + group_id if group_id == first_id else group_id): wells
        for group_id, wells in members.items()
    }
    other = replace(artifact, groups=replace(artifact.groups, groups=renamed))
    assert artifact_hash(other) != artifact_hash(artifact)


def test_a_seed_change_is_a_different_artifact(influence: Lambda) -> None:
    first, _ = build_artifact(influence, GroupingParams(seed=7))
    second, _ = build_artifact(influence, GroupingParams(seed=8))
    assert first.groups.groups == second.groups.groups
    assert artifact_hash(first) != artifact_hash(second)


def test_an_artifact_without_a_window_is_refused(artifact: GroupsArtifact) -> None:
    payload = to_payload(artifact)
    del payload["provenance"]["window_start"]
    payload.pop("artifact_hash")
    with pytest.raises(GroupsProvenanceError, match="окна применимости"):
        from_payload(payload)


def test_an_artifact_without_provenance_at_all_is_refused(
    artifact: GroupsArtifact,
) -> None:
    payload = to_payload(artifact)
    del payload["provenance"]
    with pytest.raises(GroupsArtifactError, match="нет поля provenance"):
        from_payload(payload)


def test_an_inverted_window_is_refused() -> None:
    with pytest.raises(GroupsProvenanceError, match="окно применимости"):
        GroupsProvenance(
            window_start=WINDOW_END,
            window_end=WINDOW_START,
            algorithm=ALGORITHM_NAME,
            algorithm_version=ALGORITHM_VERSION,
            seed=0,
            merge_overlap=0.5,
            membership_share=0.25,
        )


def test_an_unparsable_window_is_refused(artifact: GroupsArtifact) -> None:
    payload = to_payload(artifact)
    payload["provenance"]["window_end"] = "не дата"
    payload.pop("artifact_hash")
    with pytest.raises(GroupsProvenanceError, match="не разбирается как дата"):
        from_payload(payload)


def test_the_window_survives_the_round_trip(artifact: GroupsArtifact) -> None:
    restored = loads(dumps(artifact))
    assert restored.window == artifact.window
    assert restored.provenance.window_start == WINDOW_START
    assert restored.provenance.window_end == WINDOW_END


def test_an_artifact_of_another_window_is_not_applied_to_this_lambda(
    artifact: GroupsArtifact,
) -> None:
    other_window = block_lambda(
        n_blocks=3,
        injectors_per_block=2,
        producers_per_block=4,
        window_start=LATER_START,
        window_end=LATER_END,
    )
    with pytest.raises(GroupsProvenanceError, match="не совпадает"):
        verify_against_lambda(artifact, other_window)


def test_an_artifact_of_the_matching_lambda_verifies(
    artifact: GroupsArtifact, influence: Lambda
) -> None:
    verify_against_lambda(artifact, influence)


def test_an_artifact_of_another_lambda_is_recognised(
    artifact: GroupsArtifact,
) -> None:
    other = block_lambda(
        n_blocks=3, injectors_per_block=2, producers_per_block=5
    )
    with pytest.raises(GroupsProvenanceError, match="другой матрицей"):
        verify_against_lambda(artifact, other)


def test_an_artifact_of_another_algorithm_version_is_recognised(
    artifact: GroupsArtifact,
) -> None:
    stale = replace(
        artifact,
        provenance=replace(artifact.provenance, algorithm_version="0.0"),
    )
    assert is_current(artifact) is True
    assert is_current(stale) is False
    with pytest.raises(GroupsProvenanceError, match="версия алгоритма"):
        require_current(stale)


def test_an_artifact_of_another_algorithm_is_recognised(
    artifact: GroupsArtifact,
) -> None:
    alien = replace(
        artifact,
        provenance=replace(artifact.provenance, algorithm="spectral-clustering"),
    )
    assert is_current(alien) is False
    with pytest.raises(GroupsProvenanceError, match="порождён алгоритмом"):
        require_current(alien)


def test_an_artifact_of_other_parameters_is_recognised(influence: Lambda) -> None:
    built, _ = build_artifact(influence, GroupingParams(merge_overlap=0.9))
    assert matches_params(built, GroupingParams(merge_overlap=0.9)) is True
    assert matches_params(built, GroupingParams()) is False
    with pytest.raises(GroupsProvenanceError, match="построен с параметрами"):
        require_params(built, GroupingParams())


def test_a_stale_artifact_is_not_reused_silently(influence: Lambda) -> None:
    fresh, _ = build_artifact(influence)
    assert reusable_for(fresh, influence, GroupingParams()) is True
    stale = replace(
        fresh, provenance=replace(fresh.provenance, algorithm_version="0.0")
    )
    assert reusable_for(stale, influence, GroupingParams()) is False
    other_params = replace(
        fresh, provenance=replace(fresh.provenance, seed=99)
    )
    assert reusable_for(other_params, influence, GroupingParams()) is False
    other_lambda = block_lambda(
        n_blocks=4, injectors_per_block=2, producers_per_block=4
    )
    assert reusable_for(fresh, other_lambda, GroupingParams()) is False


def test_the_version_travels_in_the_serialized_form(artifact: GroupsArtifact) -> None:
    payload = json.loads(dumps(artifact))
    assert payload["provenance"]["algorithm_version"] == ALGORITHM_VERSION
    assert payload["provenance"]["algorithm"] == ALGORITHM_NAME
    assert payload["format"] == ARTIFACT_FORMAT


def test_a_foreign_format_is_refused(artifact: GroupsArtifact) -> None:
    payload = to_payload(artifact)
    payload["format"] = "чужой.формат"
    with pytest.raises(GroupsArtifactError, match="нераспознанный формат"):
        from_payload(payload)


def test_a_tampered_artifact_hash_is_refused(artifact: GroupsArtifact) -> None:
    payload = to_payload(artifact)
    payload["artifact_hash"] = "0" * 64
    with pytest.raises(GroupsArtifactError, match="не сходится"):
        from_payload(payload)


def test_a_tampered_membership_is_caught_by_the_declared_hash(
    artifact: GroupsArtifact,
) -> None:
    payload = to_payload(artifact)
    victim = sorted(payload["groups"])[0]
    payload["groups"][victim] = payload["groups"][victim][:-1]
    with pytest.raises(GroupsArtifactError, match="не сходится"):
        from_payload(payload)


def test_loading_checks_that_every_well_is_covered(artifact: GroupsArtifact) -> None:
    payload = normalized_payload(artifact)
    victim = sorted(payload["groups"])[0]
    dropped = payload["groups"][victim][-1]
    payload["groups"][victim] = payload["groups"][victim][:-1]
    payload["groups"] = {
        group_id: [well for well in members if well != dropped]
        for group_id, members in payload["groups"].items()
    }
    payload["group_hash"] = artifact.groups.group_hash
    with pytest.raises(GroupsArtifactError, match="вне участков"):
        from_payload(payload)


def test_loading_refuses_an_empty_group(artifact: GroupsArtifact) -> None:
    payload = normalized_payload(artifact)
    payload["groups"]["G9"] = []
    payload["group_hash"] = artifact.groups.group_hash
    with pytest.raises(GroupsArtifactError, match="пуст"):
        from_payload(payload)


def test_loading_refuses_a_well_outside_the_fund(artifact: GroupsArtifact) -> None:
    payload = normalized_payload(artifact)
    victim = sorted(payload["groups"])[0]
    payload["groups"][victim] = payload["groups"][victim] + ["чужая"]
    payload["group_hash"] = artifact.groups.group_hash
    with pytest.raises(GroupsArtifactError, match="вне фонда"):
        from_payload(payload)


def test_the_injector_invariant_is_checked_against_the_lambda(
    influence: Lambda, artifact: GroupsArtifact
) -> None:
    producers_only = {
        "G1": tuple(sorted(influence.producers)),
        "G2": tuple(sorted(influence.injectors)),
    }
    broken = replace(
        artifact, groups=replace(artifact.groups, groups=producers_only)
    )
    with pytest.raises(ValueError, match="без нагнетательной"):
        verify_against_lambda(broken, influence)


def test_an_uncovered_well_is_caught_against_the_lambda(
    influence: Lambda, artifact: GroupsArtifact
) -> None:
    trimmed = dict(artifact.groups.groups)
    victim = sorted(trimmed)[0]
    trimmed[victim] = tuple(trimmed[victim][1:])
    broken = replace(artifact, groups=replace(artifact.groups, groups=trimmed))
    with pytest.raises(ValueError, match="вне участков"):
        verify_against_lambda(broken, influence)


def test_a_hash_that_is_not_sha256_is_refused(artifact: GroupsArtifact) -> None:
    with pytest.raises(GroupsArtifactError, match="SHA-256"):
        replace(artifact, groups=replace(artifact.groups, group_hash="короткий"))
    with pytest.raises(GroupsArtifactError, match="SHA-256"):
        replace(artifact, groups=replace(artifact.groups, lambda_hash="Z" * 64))


def test_the_same_lambda_and_seed_are_deterministic(influence: Lambda) -> None:
    first, _ = build_artifact(influence, GroupingParams(seed=7))
    second, _ = build_artifact(influence, GroupingParams(seed=7))
    assert first == second
    assert artifact_hash(first) == artifact_hash(second)
    assert dumps(first) == dumps(second)


def test_determinism_survives_a_reordered_lambda() -> None:
    straight = lambda_of(
        producers=("p1", "p2"),
        injectors=("i1", "i2"),
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    flipped = lambda_of(
        producers=("p2", "p1"),
        injectors=("i2", "i1"),
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    first, _ = build_artifact(straight)
    second, _ = build_artifact(flipped)
    assert normalized_payload(first)["groups"] == normalized_payload(second)["groups"]


def test_the_cache_key_moves_with_the_artifact(
    influence: Lambda, artifact: GroupsArtifact
) -> None:
    deck_hash = "a" * 64
    other = block_lambda(
        n_blocks=4, injectors_per_block=2, producers_per_block=4
    )
    second, _ = build_artifact(other)
    assert cache_key(artifact, deck_hash) != cache_key(second, deck_hash)
    assert cache_key(artifact, deck_hash) == cache_key(artifact, deck_hash)


def test_the_cache_key_moves_with_the_deck(artifact: GroupsArtifact) -> None:
    assert cache_key(artifact, "a" * 64) != cache_key(artifact, "b" * 64)
    assert len(cache_key(artifact, "a" * 64)) == 64


def test_the_cache_key_refuses_a_part_that_is_not_a_hash(
    artifact: GroupsArtifact,
) -> None:
    with pytest.raises(GroupsArtifactError, match="ключа кеша"):
        cache_key(artifact, "дек")


def test_rehash_reattaches_the_artifact_to_a_recomputed_lambda(
    influence: Lambda, artifact: GroupsArtifact
) -> None:
    second_batch = replace(influence, stability=0.55, condition_number=11.0)
    moved = rehash(artifact, second_batch)
    assert moved.groups.groups == artifact.groups.groups
    assert moved.groups.lambda_hash == lambda_hash(second_batch)
    verify_against_lambda(moved, second_batch)


def test_the_provenance_helper_agrees_with_the_builder(influence: Lambda) -> None:
    params = GroupingParams(merge_overlap=0.7, membership_share=0.3, seed=5)
    built, _ = build_artifact(influence, params)
    assert built.provenance == provenance_of(influence, params)
    assert built.provenance.params == params


def test_the_artifact_covers_the_wells_outside_lambda_too(influence: Lambda) -> None:
    extra = ("p_shut_in",)
    built, report = build_artifact(influence, extra_wells=extra)
    assert "p_shut_in" in built.fund
    assert report.coverage == len(built.fund)
    restored = loads(dumps(built))
    assert restored.fund == built.fund


def test_the_real_deck_fund_round_trips(deck) -> None:
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
    built, report = build_artifact(influence, extra_wells=fund)
    assert report.coverage == report.n_wells == len(fund)
    restored = loads(dumps(built))
    assert restored == built
    assert len(restored.fund) == len(fund)
    verify_against_lambda(restored, influence)


def test_a_groups_object_without_the_envelope_is_not_an_artifact(
    influence: Lambda,
) -> None:
    bare, _ = build_groups(influence)
    assert isinstance(bare, Groups)
    assert not hasattr(bare, "provenance")
