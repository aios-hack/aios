from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind, Schedule
from backend.contexts.connectivity.domain.connectivity import Lambda
from backend.contexts.schedule.domain.schedule import (
    Availability,
    OperatingStatus,
    Role,
    ScheduleMeta,
    WellState,
)
from backend.contexts.optimization.infrastructure.artifacts import (
    LAMBDA_PATH_ENV,
    LAMBDA_SELECTION_ENV,
    LAMBDA_SELECTION_FORMAT,
    RuntimeArtifactError,
    resolve_lambda_selection,
)
from backend.contexts.optimization.application.search_use_case import (
    ConnectivitySearchError,
    _baseline_injection_rates,
    _connectivity_groups,
    _injection_transfer_plan,
    _lambda_connectivity,
    _transfer_injection,
)
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_report import (
    DEFAULT_HOLDOUT,
    HOLDOUT_FORMAT,
    FrozenHoldoutError,
    assert_holdout_excluded,
    load_frozen_holdout,
)

REPO_LAMBDA = Path("data/lambda-window-2007/lambda.json")
REPO_SELECTION = Path("config/lambda-selection.json")
FEATURE_CONTEXT_SHA = "164efe9c442a81eebb4663e6fef37efab5a49bb34b6741a8f8576cea5f695190"


def _write_lambda(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"matrix": []}), encoding="utf-8")


def _selection_document(lambda_path: str, **candidate: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "path": lambda_path,
        "rationale": "selected as an export from the model feature context",
    }
    entry.update(candidate)
    return {
        "format": LAMBDA_SELECTION_FORMAT,
        "selected": "feature-context-export",
        "candidates": {"feature-context-export": entry},
    }


def _environment(tmp_path: Path, selection: Path | None) -> dict[str, str]:
    env = {"AIOS_PROJECT_ROOT": str(tmp_path)}
    if selection is not None:
        env[LAMBDA_SELECTION_ENV] = str(selection)
    return env


def test_lambda_path_comes_from_configuration_not_module_constant(tmp_path) -> None:
    lambda_path = tmp_path / "measured" / "lambda.json"
    _write_lambda(lambda_path)
    selection = tmp_path / "lambda-selection.json"
    selection.write_text(
        json.dumps(_selection_document(str(lambda_path))), encoding="utf-8"
    )

    decision = resolve_lambda_selection(_environment(tmp_path, selection))

    assert decision.path == lambda_path
    assert decision.origin == "selection-config"
    assert decision.selection_path == selection


def test_selection_records_rationale_in_provenance(tmp_path) -> None:
    lambda_path = tmp_path / "lambda.json"
    _write_lambda(lambda_path)
    selection = tmp_path / "selection.json"
    document = _selection_document(str(lambda_path))
    document["candidates"]["feature-context-export"]["rationale"] = (
        "lambda was exported from the same feature context the weights were trained on"
    )
    selection.write_text(json.dumps(document), encoding="utf-8")

    provenance = resolve_lambda_selection(
        _environment(tmp_path, selection)
    ).as_provenance()

    assert provenance["lambda_path"] == str(lambda_path)
    assert provenance["lambda_selection"] == "feature-context-export"
    assert provenance["lambda_selection_origin"] == "selection-config"
    assert "feature context" in provenance["lambda_selection_rationale"]


def test_candidate_without_rationale_is_refused(tmp_path) -> None:
    lambda_path = tmp_path / "lambda.json"
    _write_lambda(lambda_path)
    selection = tmp_path / "selection.json"
    document = _selection_document(str(lambda_path))
    document["candidates"]["feature-context-export"].pop("rationale")
    selection.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeArtifactError, match="without a rationale"):
        resolve_lambda_selection(_environment(tmp_path, selection))


def test_missing_selection_config_is_an_error_not_a_default(tmp_path) -> None:
    with pytest.raises(RuntimeArtifactError, match="selection configuration"):
        resolve_lambda_selection(_environment(tmp_path, None))


def test_selection_verifies_lambda_against_feature_context(tmp_path) -> None:
    lambda_path = tmp_path / "lambda.json"
    _write_lambda(lambda_path)
    context = tmp_path / "feature_context.json"
    context.write_bytes(b"{}")
    digest = hashlib.sha256(context.read_bytes()).hexdigest()
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            _selection_document(
                str(lambda_path), expected_feature_context_sha256=digest
            )
        ),
        encoding="utf-8",
    )

    decision = resolve_lambda_selection(
        _environment(tmp_path, selection), feature_context=context
    )

    assert decision.feature_context_match == "identical"
    assert decision.as_provenance()["lambda_feature_context_match"] == "identical"


def test_lambda_desynchronised_from_feature_context_is_refused(tmp_path) -> None:
    lambda_path = tmp_path / "lambda.json"
    _write_lambda(lambda_path)
    context = tmp_path / "feature_context.json"
    context.write_bytes(b"{}")
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            _selection_document(
                str(lambda_path), expected_feature_context_sha256="0" * 64
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeArtifactError, match="diverged"):
        resolve_lambda_selection(
            _environment(tmp_path, selection), feature_context=context
        )


def test_environment_override_is_marked_as_unverified(tmp_path) -> None:
    lambda_path = tmp_path / "operator" / "lambda.json"
    _write_lambda(lambda_path)
    env = _environment(tmp_path, None)
    env[LAMBDA_PATH_ENV] = str(lambda_path)

    decision = resolve_lambda_selection(env)

    assert decision.path == lambda_path
    assert decision.origin == "environment-override"
    assert decision.feature_context_match == "not-checked"


def test_repository_selection_names_the_feature_context_export() -> None:
    if not REPO_SELECTION.is_file() or not REPO_LAMBDA.is_file():
        pytest.skip("the working copy has no lambda selection configuration or lambda itself")
    document = json.loads(REPO_SELECTION.read_text(encoding="utf-8"))

    assert document["format"] == LAMBDA_SELECTION_FORMAT
    assert document["selected"] == "feature-context-export"
    candidate = document["candidates"]["feature-context-export"]
    assert candidate["expected_feature_context_sha256"] == FEATURE_CONTEXT_SHA
    assert "feature_context_sha256" in candidate["rationale"]
    exported = json.loads(REPO_LAMBDA.read_text(encoding="utf-8"))
    assert (
        exported["provenance"]["feature_context_sha256"] == FEATURE_CONTEXT_SHA
    )
    assert exported["lag_months"] == 0


def _lambda(strengths: dict[str, float]) -> Lambda:
    injectors = tuple(strengths)
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2025, 9, 1),
        producers=("P1", "P2"),
        injectors=injectors,
        matrix=(
            tuple(strengths[well] * 0.75 for well in injectors),
            tuple(strengths[well] * 0.25 for well in injectors),
        ),
        lag_months=0,
        amplitude=1.0,
        stability=0.5,
        rank=len(injectors),
        condition_number=1.0,
        achievability_ok={well: True for well in injectors},
    )


def _schedule(rates: dict[str, float]) -> Schedule:
    wells = tuple(sorted(rates))
    return Schedule(
        meta=ScheduleMeta(wells=wells),
        initial_state={
            well: WellState(
                availability=Availability.AVAILABLE,
                role=Role.INJ,
                operating_status=OperatingStatus.OPEN,
                setpoint=rates[well],
            )
            for well in wells
        },
        fixed_deck_events=(),
        control_events=tuple(
            ControlEvent(
                control_step=0, well=well, kind=EventKind.SET_RATE, value=rates[well]
            )
            for well in wells
        ),
    )


STRENGTHS = {"I1": 4.0, "I2": 3.0, "I3": 2.0, "I4": 1.0, "I5": 0.5, "I6": 0.25}
RATES = {well: 400.0 for well in STRENGTHS}


def test_connectivity_ranks_injectors_by_lambda_not_by_well_name() -> None:
    strength = _lambda_connectivity(_lambda(STRENGTHS))

    ordered = sorted(strength, key=lambda well: -strength[well])
    assert ordered == ["I1", "I2", "I3", "I4", "I5", "I6"]
    assert strength["I1"] == pytest.approx(4.0)
    assert strength["I6"] == pytest.approx(0.25)


def test_fallback_candidates_differ_by_lambda_group_not_by_well_index() -> None:
    lambda_ = _lambda(STRENGTHS)
    groups = _connectivity_groups(_lambda_connectivity(lambda_))
    transfers = _injection_transfer_plan(lambda_, _schedule(RATES), budget=4)

    assert transfers
    for donor, receiver, volume in transfers:
        assert volume > 0.0
        assert STRENGTHS[receiver] > STRENGTHS[donor]
    assert transfers[0][0] == "I6"
    assert transfers[0][1] == "I1"
    assert groups[transfers[0][0]] == "low"
    assert groups[transfers[0][1]] == "high"
    donors = [donor for donor, _, _ in transfers]
    assert donors != sorted(donors)


def test_transfer_is_budget_neutral_and_moves_water_to_high_connectivity() -> None:
    lambda_ = _lambda(STRENGTHS)
    baseline = _schedule(RATES)
    donor, receiver, volume = _injection_transfer_plan(
        lambda_, baseline, budget=2
    )[0]

    moved = _transfer_injection(baseline, donor, receiver, volume)
    before = _baseline_injection_rates(baseline)
    after = _baseline_injection_rates(moved)

    assert after[donor] == pytest.approx(before[donor] - volume)
    assert after[receiver] == pytest.approx(before[receiver] + volume)
    assert sum(after.values()) == pytest.approx(sum(before.values()))
    assert STRENGTHS[receiver] > STRENGTHS[donor]


def test_candidates_are_distinct_schedules() -> None:
    lambda_ = _lambda(STRENGTHS)
    baseline = _schedule(RATES)
    transfers = _injection_transfer_plan(lambda_, baseline, budget=4)

    schedules = [
        _baseline_injection_rates(_transfer_injection(baseline, *transfer))
        for transfer in transfers
    ]
    seen = {tuple(sorted(rates.items())) for rates in schedules}
    assert len(seen) == len(schedules)


def test_ranking_follows_connectivity_when_it_contradicts_well_order() -> None:
    inverted = {"I1": 0.25, "I2": 0.5, "I3": 1.0, "I4": 2.0, "I5": 3.0, "I6": 4.0}
    lambda_ = _lambda(inverted)
    groups = _connectivity_groups(_lambda_connectivity(lambda_))
    transfers = _injection_transfer_plan(
        lambda_, _schedule({well: 400.0 for well in inverted}), budget=4
    )

    assert [donor for donor, _, _ in transfers] == ["I1", "I2", "I3"]
    assert [receiver for _, receiver, _ in transfers] == ["I6", "I5", "I4"]
    assert groups["I6"] == "high"
    assert groups["I1"] == "low"


def test_lambda_without_injectors_is_refused_not_replaced_by_index_sweep() -> None:
    empty = replace(_lambda(STRENGTHS), injectors=(), matrix=((), ()))

    with pytest.raises(ConnectivitySearchError, match="contains no injector"):
        _lambda_connectivity(empty)


def test_single_active_injector_is_refused() -> None:
    lambda_ = _lambda(STRENGTHS)
    schedule = _schedule({"I1": 400.0, "I2": 0.0, "I3": 0.0, "I4": 0.0, "I5": 0.0, "I6": 0.0})

    with pytest.raises(ConnectivitySearchError, match="nobody to redistribute"):
        _injection_transfer_plan(lambda_, schedule, budget=4)


def _holdout_document(hashes: list[str], **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "format": HOLDOUT_FORMAT,
        "populated": bool(hashes),
        "canonical_schedule_hashes": hashes,
        "unpopulated_reason": "there are no suitable OPM runs on disk",
    }
    document.update(overrides)
    return document


def _holdout_file(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "surrogate-holdout.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_training_on_holdout_is_an_error(tmp_path) -> None:
    frozen = "a" * 64
    holdout = load_frozen_holdout(_holdout_file(tmp_path, _holdout_document([frozen])))

    with pytest.raises(FrozenHoldoutError, match="schedules of the frozen holdout"):
        assert_holdout_excluded(holdout, [frozen, "b" * 64], "training set")


def test_disjoint_training_set_passes(tmp_path) -> None:
    holdout = load_frozen_holdout(
        _holdout_file(tmp_path, _holdout_document(["a" * 64]))
    )

    assert_holdout_excluded(holdout, ["b" * 64, "c" * 64], "training set")


def test_empty_holdout_is_valid_and_marked_unpopulated(tmp_path) -> None:
    holdout = load_frozen_holdout(_holdout_file(tmp_path, _holdout_document([])))

    assert holdout.populated is False
    assert holdout.hashes == frozenset()
    assert "OPM" in holdout.reason
    provenance = holdout.as_provenance()
    assert provenance["frozen_holdout_populated"] is False
    assert provenance["frozen_holdout_size"] == 0


def test_empty_holdout_without_reason_is_refused(tmp_path) -> None:
    document = _holdout_document([])
    document.pop("unpopulated_reason")

    with pytest.raises(FrozenHoldoutError, match="must explain why"):
        load_frozen_holdout(_holdout_file(tmp_path, document))


def test_populated_flag_must_agree_with_the_list(tmp_path) -> None:
    document = _holdout_document(["a" * 64], populated=False)

    with pytest.raises(FrozenHoldoutError, match="diverges from"):
        load_frozen_holdout(_holdout_file(tmp_path, document))


def test_missing_holdout_file_is_an_error(tmp_path) -> None:
    with pytest.raises(FrozenHoldoutError, match="there is no frozen holdout"):
        load_frozen_holdout(tmp_path / "absent.json")


def test_non_hash_entry_is_refused(tmp_path) -> None:
    document = _holdout_document(["not-a-hash"])

    with pytest.raises(FrozenHoldoutError, match="canonical_schedule_hash"):
        load_frozen_holdout(_holdout_file(tmp_path, document))


def test_repository_holdout_is_valid_and_declared_unpopulated() -> None:
    if not DEFAULT_HOLDOUT.is_file():
        pytest.skip("the working copy has no frozen holdout")
    holdout = load_frozen_holdout(DEFAULT_HOLDOUT)

    assert holdout.populated is False
    assert holdout.hashes == frozenset()
    assert holdout.reason


def test_lambda_lag_is_zero_so_feature_shift_changes_nothing() -> None:
    if not REPO_LAMBDA.is_file():
        pytest.skip("the working copy has no measured lambda")
    exported = json.loads(REPO_LAMBDA.read_text(encoding="utf-8"))

    assert exported["lag_months"] == 0
