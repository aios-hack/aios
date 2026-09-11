from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from backend.core.contracts import Groups, Lambda, RunArtifact
from backend.core.paths import data_root
from backend.contexts.connectivity.application.campaign import CampaignError
from backend.contexts.connectivity.domain.groups import (
    DEFAULT_QUANTILE_GRID,
    GroupingParams,
    build_groups,
    group_hash,
    lambda_hash,
    sweep_quantiles,
    weight_threshold,
)
from backend.contexts.connectivity.domain.measure import (
    EXTRAPOLATION,
    PARTIAL_EXTRAPOLATION,
    WITHIN_WINDOW,
    load_lambda,
    save_lambda,
    verify_artifact_id,
    window_applicability,
)
from tests.backend.contexts.connectivity.test_lambda_provenance import (
    MEASURED_AT,
    RUN_IDS,
    lambda_of,
    report_of,
)
from tests.support.backend.showcase_fixtures import make_synthetic_artifact
from backend.contexts.showcase.application.exporters.graph_view import (
    build_lambda_graph,
    export_graph_json,
    file_sha256,
)

REAL_LAMBDA = data_root() / "lambda-window-2007" / "lambda.json"

PLACEHOLDER_HASH = "0" * 64


def horizon(start: date, end: date) -> tuple[date, ...]:
    months: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(date(year, month, 1))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return tuple(months)


def real_lambda() -> Lambda:
    if not REAL_LAMBDA.is_file():
        pytest.skip(f"нет измеренной связности по пути {REAL_LAMBDA}")
    return load_lambda(REAL_LAMBDA)


def dense_lambda() -> Lambda:
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2009, 1, 1),
        producers=("P1", "P2", "P3", "P4"),
        injectors=("I1", "I2", "I3", "I4"),
        matrix=(
            (0.90, 0.80, 0.70, 0.60),
            (0.85, 0.75, 0.65, 0.55),
            (0.20, 0.18, 0.16, 0.14),
            (0.10, 0.09, 0.08, 0.07),
        ),
        lag_months=2,
        amplitude=10.0,
        stability=0.99,
        rank=4,
        condition_number=8.0,
        achievability_ok={well: True for well in ("I1", "I2", "I3", "I4")},
    )


def artifact_with(influence: Lambda) -> RunArtifact:
    artifact = make_synthetic_artifact(n_wells=6)
    groups = Groups(
        groups={"G1": ("I1", "P1"), "G2": ("I2", "P2")},
        lambda_hash=PLACEHOLDER_HASH,
        group_hash=PLACEHOLDER_HASH,
    )
    return replace(artifact, lambda_=influence, groups=groups)


def test_window_outside_the_horizon_is_extrapolation() -> None:
    influence = lambda_of(window_start=date(2007, 1, 1), window_end=date(2009, 1, 1))
    verdict = window_applicability(
        influence, horizon(date(2010, 1, 1), date(2025, 9, 1))
    )
    assert verdict.verdict == EXTRAPOLATION
    assert verdict.is_extrapolation
    assert verdict.covered_share == 0.0
    assert verdict.months_after == 200
    assert "экстраполяция" in verdict.detail


def test_window_covering_the_horizon_is_within_measurement() -> None:
    influence = lambda_of(window_start=date(2007, 1, 1), window_end=date(2025, 9, 1))
    verdict = window_applicability(
        influence, horizon(date(2008, 1, 1), date(2024, 12, 1))
    )
    assert verdict.verdict == WITHIN_WINDOW
    assert not verdict.is_extrapolation
    assert verdict.covered_share == 1.0
    assert verdict.months_before == 0
    assert verdict.months_after == 0


def test_partly_covered_horizon_names_the_uncovered_months() -> None:
    influence = lambda_of(window_start=date(2007, 1, 1), window_end=date(2009, 1, 1))
    verdict = window_applicability(
        influence, horizon(date(2007, 1, 1), date(2025, 9, 1))
    )
    assert verdict.verdict == PARTIAL_EXTRAPOLATION
    assert verdict.is_extrapolation
    assert 0.0 < verdict.covered_share < 1.0
    assert verdict.months_after == 200


def test_real_window_on_the_case_horizon_lands_in_the_manifest() -> None:
    influence = real_lambda()
    verdict = window_applicability(
        influence, horizon(date(2007, 1, 1), date(2025, 9, 1))
    )
    record = verdict.as_provenance()
    assert record["lambda_window_applicability"] == verdict.verdict
    assert record["lambda_window_measured"] == (
        f"{influence.window_start}..{influence.window_end}"
    )
    assert record["lambda_window_horizon"] == "2007-01-01..2025-09-01"
    assert set(record) == {
        "lambda_window_applicability",
        "lambda_window_applicability_detail",
        "lambda_window_measured",
        "lambda_window_horizon",
        "lambda_window_covered_share",
        "lambda_window_months_outside",
    }
    assert all(isinstance(value, str) for value in record.values())


def test_empty_horizon_is_an_error_not_a_verdict() -> None:
    with pytest.raises(CampaignError, match="горизонт кейса пуст"):
        window_applicability(lambda_of(), ())


def test_graph_json_carries_artifact_id_and_file_hash(tmp_path) -> None:
    influence = lambda_of()
    path = save_lambda(
        report_of(influence),
        tmp_path / "lambda.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    out = export_graph_json(artifact_with(influence), tmp_path / "graph.json", path)
    graph = json.loads(out.read_text(encoding="utf-8"))
    provenance = graph["provenance"]
    assert provenance["artifact_id"] == lambda_hash(influence)
    assert provenance["lambda_file_sha256"] == file_sha256(path)
    assert provenance["lambda_path"] == str(path)
    assert provenance["window_start"] == influence.window_start.isoformat()
    assert provenance["window_end"] == influence.window_end.isoformat()
    assert provenance["lag_months"] == influence.lag_months


def test_graph_provenance_distinguishes_two_different_matrices(tmp_path) -> None:
    first = lambda_of()
    second = lambda_of(matrix=((0.9, -0.2), (0.1, 0.4)))
    first_path = save_lambda(
        report_of(first),
        tmp_path / "first.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    second_path = save_lambda(
        report_of(second),
        tmp_path / "second.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    left = build_lambda_graph(artifact_with(first), first_path)["provenance"]
    right = build_lambda_graph(artifact_with(second), second_path)["provenance"]
    assert left["artifact_id"] != right["artifact_id"]
    assert left["lambda_file_sha256"] != right["lambda_file_sha256"]


def test_graph_without_a_path_still_names_the_matrix() -> None:
    influence = lambda_of()
    provenance = build_lambda_graph(artifact_with(influence))["provenance"]
    assert provenance["artifact_id"] == lambda_hash(influence)
    assert provenance["lambda_path"] is None
    assert provenance["lambda_file_sha256"] is None


def test_graph_refuses_to_sign_a_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="нет по пути"):
        build_lambda_graph(artifact_with(lambda_of()), tmp_path / "missing.json")


def test_dense_lambda_collapses_into_one_group() -> None:
    _, report = build_groups(dense_lambda())
    assert report.n_groups == 1
    assert report.collapsed
    assert report.weight_quantile is None
    assert report.weight_cut is None


def test_quantile_threshold_splits_a_dense_matrix() -> None:
    influence = dense_lambda()
    _, loose = build_groups(influence, GroupingParams(weight_quantile=0.0))
    _, tight = build_groups(influence, GroupingParams(weight_quantile=0.9))
    assert loose.n_groups == 1
    assert tight.n_groups > loose.n_groups
    assert tight.kept_edges < loose.kept_edges
    assert tight.weight_cut is not None
    assert tight.weight_cut > 0.0


def test_weight_threshold_grows_with_the_quantile() -> None:
    influence = dense_lambda()
    cuts = [weight_threshold(influence, quantile) for quantile in (0.0, 0.25, 0.5, 0.9)]
    assert cuts == sorted(cuts)
    assert cuts[0] == min(
        value for row in influence.matrix for value in row if value > 0.0
    )


def test_weight_threshold_refuses_a_matrix_without_positive_weights() -> None:
    empty = replace(
        dense_lambda(),
        matrix=tuple(tuple(0.0 for _ in range(4)) for _ in range(4)),
    )
    with pytest.raises(ValueError, match="положительного веса"):
        weight_threshold(empty, 0.5)


def test_quantile_outside_the_unit_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="квантиль веса"):
        GroupingParams(weight_quantile=1.0)
    with pytest.raises(ValueError, match="квантиль веса"):
        GroupingParams(weight_quantile=-0.1)


def test_quantile_moves_the_group_hash() -> None:
    influence = dense_lambda()
    plain, _ = build_groups(influence)
    assert plain.group_hash == group_hash(plain.groups, influence, GroupingParams())
    assert plain.group_hash != group_hash(
        plain.groups, influence, GroupingParams(weight_quantile=0.5)
    )


def test_real_matrix_gives_different_group_counts_by_threshold() -> None:
    influence = real_lambda()
    sweep = sweep_quantiles(influence)
    assert sweep.baseline_groups == 1
    assert len({step.n_groups for step in sweep.steps}) > 1
    assert sweep.steps[0].n_groups == 1
    assert sweep.steps[-1].n_groups > 1
    assert sweep.split_quantile is not None
    assert sweep.split_cut is not None
    kept = [step.kept_edges for step in sweep.steps]
    assert kept == sorted(kept, reverse=True)
    for step in sweep.steps:
        assert step.largest_group <= sweep.n_wells
        if step.n_groups == 1:
            assert step.largest_group == sweep.n_wells


def test_real_matrix_stops_being_one_group_at_a_reported_threshold() -> None:
    influence = real_lambda()
    sweep = sweep_quantiles(influence)
    split = sweep.split_quantile
    assert split is not None
    _, at_split = build_groups(influence, GroupingParams(weight_quantile=split))
    assert at_split.n_groups > 1
    assert all(step.n_groups == 1 for step in sweep.steps if step.quantile < split)


def test_sweep_refuses_an_empty_grid() -> None:
    with pytest.raises(ValueError, match="сетка квантилей пуста"):
        sweep_quantiles(dense_lambda(), ())


def test_default_grid_starts_at_zero_and_stays_below_one() -> None:
    assert DEFAULT_QUANTILE_GRID[0] == 0.0
    assert max(DEFAULT_QUANTILE_GRID) < 1.0
    assert list(DEFAULT_QUANTILE_GRID) == sorted(DEFAULT_QUANTILE_GRID)


def test_tampered_content_is_caught_by_verify_artifact_id(tmp_path) -> None:
    influence = lambda_of()
    path = save_lambda(
        report_of(influence),
        tmp_path / "lambda.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    assert verify_artifact_id(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["matrix"][0][0] += 0.5
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert not verify_artifact_id(path)


def test_tampered_window_is_caught_by_verify_artifact_id(tmp_path) -> None:
    path = save_lambda(
        report_of(lambda_of()),
        tmp_path / "lambda.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["window_end"] = "2025-09-01"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert not verify_artifact_id(path)


def test_file_hash_changes_when_the_bytes_change(tmp_path) -> None:
    path = Path(tmp_path) / "lambda.json"
    path.write_text("{}", encoding="utf-8")
    before = file_sha256(path)
    path.write_text('{"a": 1}', encoding="utf-8")
    assert file_sha256(path) != before
