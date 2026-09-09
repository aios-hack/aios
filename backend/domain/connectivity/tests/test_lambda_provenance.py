from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from backend.core.contracts import Lambda
from backend.domain.connectivity.campaign import CampaignError
from backend.domain.connectivity.measure import (
    ARTIFACT_FORMAT,
    MEASURE_CODE_VERSION,
    PROVENANCE_FIELDS,
    LambdaProvenance,
    MeasurementReport,
    artifact_id,
    load_lambda,
    load_lambda_provenance,
    load_lambda_with_provenance,
    save_lambda,
    verify_artifact_id,
)

from tools.lambda_compare import (
    LambdaCompareError,
    average_ranks,
    compare,
    overlap,
    sign_agreement,
    spearman,
)

WINDOW_START = date(2007, 1, 1)
WINDOW_END = date(2009, 1, 1)
MEASURED_AT = date(2026, 8, 16)
RUN_IDS = ("20260816T200926-8b4da543d1ed", "20260816T201455-2f9a1c77b410")


def lambda_of(
    producers: tuple[str, ...] = ("P1", "P2"),
    injectors: tuple[str, ...] = ("I1", "I2"),
    matrix: tuple[tuple[float, ...], ...] = ((0.5, -0.2), (0.1, 0.4)),
    lag_months: int = 2,
    window_start: date = WINDOW_START,
    window_end: date = WINDOW_END,
) -> Lambda:
    return Lambda(
        window_start=window_start,
        window_end=window_end,
        producers=producers,
        injectors=injectors,
        matrix=matrix,
        lag_months=lag_months,
        amplitude=10.0,
        stability=0.9929,
        rank=len(injectors),
        condition_number=7.5,
        achievability_ok={well: True for well in injectors},
    )


def report_of(influence: Lambda) -> MeasurementReport:
    return MeasurementReport(
        influence=influence,
        lag_scan=((0, 0.41), (1, 0.63), (2, 0.88)),
        n_runs_by_batch=(54, 54),
        unreachable=(),
        unmoved=(),
    )


def legacy_payload(influence: Lambda) -> dict[str, object]:
    return {
        "window_start": influence.window_start.isoformat(),
        "window_end": influence.window_end.isoformat(),
        "lag_months": influence.lag_months,
        "amplitude": influence.amplitude,
        "rank": influence.rank,
        "condition_number": influence.condition_number,
        "stability": influence.stability,
        "producers": list(influence.producers),
        "injectors": list(influence.injectors),
        "matrix": [list(row) for row in influence.matrix],
        "achievability_ok": dict(influence.achievability_ok),
        "lag_scan": [[0, 0.41], [2, 0.88]],
        "n_runs_by_batch": [54, 54],
    }


def write_legacy(path: Path, influence: Lambda) -> Path:
    path.write_text(
        json.dumps(legacy_payload(influence), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def test_legacy_artifact_still_loads_as_a_matrix(tmp_path) -> None:
    influence = lambda_of()
    path = write_legacy(tmp_path / "lambda.json", influence)
    restored = load_lambda(path)
    assert restored.matrix == influence.matrix
    assert restored.producers == influence.producers
    assert restored.injectors == influence.injectors
    assert restored.lag_months == influence.lag_months
    assert restored.stability == influence.stability


def test_legacy_provenance_is_none_not_invented(tmp_path) -> None:
    path = write_legacy(tmp_path / "lambda.json", lambda_of())
    provenance = load_lambda_provenance(path)
    assert provenance.artifact_id is None
    assert provenance.measured_at is None
    assert provenance.n_runs is None
    assert provenance.source_run_ids is None
    assert provenance.code_version is None
    assert not provenance.is_recorded
    assert set(provenance.missing_fields) == set(PROVENANCE_FIELDS)


def test_legacy_measured_at_is_not_filled_with_today(tmp_path) -> None:
    path = write_legacy(tmp_path / "lambda.json", lambda_of())
    provenance = load_lambda_provenance(path)
    assert provenance.measured_at != date.today()
    assert provenance.measured_at is None


def test_legacy_artifact_id_check_reports_absence(tmp_path) -> None:
    path = write_legacy(tmp_path / "lambda.json", lambda_of())
    with pytest.raises(CampaignError, match="artifact_id не записан"):
        verify_artifact_id(path)


def test_round_trip_carries_the_new_fields(tmp_path) -> None:
    influence = lambda_of()
    path = save_lambda(
        report_of(influence),
        tmp_path / "lambda.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    restored, provenance = load_lambda_with_provenance(path)
    assert restored.matrix == influence.matrix
    assert restored.achievability_ok == influence.achievability_ok
    assert provenance.artifact_id == artifact_id(influence)
    assert provenance.measured_at == MEASURED_AT
    assert provenance.n_runs == len(RUN_IDS)
    assert provenance.source_run_ids == RUN_IDS
    assert provenance.code_version == MEASURE_CODE_VERSION
    assert provenance.is_recorded
    assert provenance.missing_fields == ()
    assert verify_artifact_id(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["artifact_format"] == ARTIFACT_FORMAT


def test_saving_without_run_ids_is_refused(tmp_path) -> None:
    with pytest.raises(CampaignError, match="без единого идентификатора"):
        save_lambda(
            report_of(lambda_of()),
            tmp_path / "lambda.json",
            measured_at=MEASURED_AT,
            source_run_ids=(),
        )


def test_repeated_run_ids_are_refused(tmp_path) -> None:
    with pytest.raises(CampaignError, match="повторяются"):
        save_lambda(
            report_of(lambda_of()),
            tmp_path / "lambda.json",
            measured_at=MEASURED_AT,
            source_run_ids=(RUN_IDS[0], RUN_IDS[0]),
        )


def test_n_runs_disagreeing_with_the_list_is_refused(tmp_path) -> None:
    path = tmp_path / "lambda.json"
    payload = legacy_payload(lambda_of())
    payload["source_run_ids"] = list(RUN_IDS)
    payload["n_runs"] = 7
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CampaignError, match="расходится со списком"):
        load_lambda_provenance(path)


def test_unreadable_measured_at_is_an_error_not_a_guess(tmp_path) -> None:
    path = tmp_path / "lambda.json"
    payload = legacy_payload(lambda_of())
    payload["measured_at"] = "когда-то в августе"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CampaignError, match="не читается"):
        load_lambda_provenance(path)


def test_partial_provenance_names_the_missing_fields(tmp_path) -> None:
    path = tmp_path / "lambda.json"
    payload = legacy_payload(lambda_of())
    payload["measured_at"] = MEASURED_AT.isoformat()
    payload["code_version"] = MEASURE_CODE_VERSION
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    provenance = load_lambda_provenance(path)
    assert provenance.measured_at == MEASURED_AT
    assert provenance.code_version == MEASURE_CODE_VERSION
    assert not provenance.is_recorded
    assert set(provenance.missing_fields) == {"artifact_id", "n_runs", "source_run_ids"}


def test_artifact_id_is_stable_for_identical_content() -> None:
    assert artifact_id(lambda_of()) == artifact_id(lambda_of())


def test_artifact_id_differs_for_a_different_matrix() -> None:
    other = lambda_of(matrix=((0.5, -0.2), (0.1, 0.9)))
    assert artifact_id(lambda_of()) != artifact_id(other)


def test_artifact_id_differs_for_a_different_window() -> None:
    other = lambda_of(window_end=date(2025, 9, 1))
    assert artifact_id(lambda_of()) != artifact_id(other)


def test_artifact_id_differs_for_a_different_lag() -> None:
    assert artifact_id(lambda_of()) != artifact_id(lambda_of(lag_months=0))


def test_artifact_id_survives_the_round_trip(tmp_path) -> None:
    influence = lambda_of()
    path = save_lambda(
        report_of(influence),
        tmp_path / "lambda.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    assert artifact_id(load_lambda(path)) == artifact_id(influence)


def test_missing_file_still_raises_instead_of_zero_matrix(tmp_path) -> None:
    with pytest.raises(CampaignError, match="ещё не отрабатывала"):
        load_lambda_provenance(tmp_path / "нет-такого.json")


def test_ranks_average_over_ties() -> None:
    assert average_ranks((10.0, 20.0, 30.0)) == (1.0, 2.0, 3.0)
    assert average_ranks((5.0, 5.0, 9.0)) == (1.5, 1.5, 3.0)
    assert average_ranks((7.0, 7.0, 7.0, 7.0)) == (2.5, 2.5, 2.5, 2.5)


def test_spearman_is_one_on_identical_ranks() -> None:
    left = (1.0, 2.0, 3.0, 4.0, 5.0)
    right = (10.0, 20.0, 30.0, 40.0, 50.0)
    assert spearman(left, right) == pytest.approx(1.0)


def test_spearman_is_minus_one_on_reversed_ranks() -> None:
    left = (1.0, 2.0, 3.0, 4.0, 5.0)
    right = (50.0, 40.0, 30.0, 20.0, 10.0)
    assert spearman(left, right) == pytest.approx(-1.0)


def test_spearman_matches_a_hand_computed_case() -> None:
    left = (1.0, 2.0, 3.0, 4.0, 5.0)
    right = (2.0, 1.0, 4.0, 3.0, 5.0)
    assert spearman(left, right) == pytest.approx(0.8)


def test_spearman_handles_ties_with_averaged_ranks() -> None:
    left = (1.0, 1.0, 2.0, 3.0)
    right = (5.0, 5.0, 6.0, 7.0)
    assert spearman(left, right) == pytest.approx(1.0)


def test_spearman_refuses_a_degenerate_series() -> None:
    with pytest.raises(LambdaCompareError, match="вырожден"):
        spearman((1.0, 1.0, 1.0), (1.0, 2.0, 3.0))


def test_spearman_refuses_a_single_observation() -> None:
    with pytest.raises(LambdaCompareError, match="определена от двух"):
        spearman((1.0,), (2.0,))


def test_sign_agreement_counts_matching_directions() -> None:
    left = (1.0, -1.0, 2.0, -2.0)
    right = (5.0, -5.0, -3.0, -4.0)
    assert sign_agreement(left, right, zero_tolerance=0.0) == pytest.approx(0.75)


def test_sign_agreement_treats_zero_as_its_own_sign() -> None:
    assert sign_agreement((0.0, 1.0), (0.0, 1.0), zero_tolerance=0.0) == pytest.approx(1.0)
    assert sign_agreement((0.0, 1.0), (1.0, 1.0), zero_tolerance=0.0) == pytest.approx(0.5)


def test_disjoint_matrices_raise_instead_of_a_silent_zero() -> None:
    left = lambda_of(producers=("P1", "P2"), injectors=("I1", "I2"))
    right = lambda_of(
        producers=("P8", "P9"),
        injectors=("I8", "I9"),
        matrix=((0.3, 0.1), (0.2, 0.7)),
    )
    with pytest.raises(LambdaCompareError, match="общая подматрица пуста"):
        overlap(left, right, zero_tolerance=0.0)


def test_disjoint_injectors_alone_are_enough_to_refuse() -> None:
    left = lambda_of(producers=("P1", "P2"), injectors=("I1", "I2"))
    right = lambda_of(
        producers=("P1", "P2"),
        injectors=("I8", "I9"),
        matrix=((0.3, 0.1), (0.2, 0.7)),
    )
    with pytest.raises(LambdaCompareError, match="общая подматрица пуста"):
        overlap(left, right, zero_tolerance=0.0)


def test_overlap_counts_edges_present_in_only_one_artifact() -> None:
    left = lambda_of(
        producers=("P1", "P2"),
        injectors=("I1", "I2"),
        matrix=((0.5, 0.0), (0.1, 0.4)),
    )
    right = lambda_of(
        producers=("P1", "P2"),
        injectors=("I1", "I2"),
        matrix=((0.5, 0.3), (0.0, 0.4)),
    )
    shared = overlap(left, right, zero_tolerance=0.0)
    assert shared.left_total_edges == 3
    assert shared.right_total_edges == 3
    assert shared.left_only_edges == 1
    assert shared.right_only_edges == 1


def test_compare_reads_both_artifacts_and_reports_provenance(tmp_path) -> None:
    left_influence = lambda_of(lag_months=2)
    right_influence = lambda_of(
        producers=("P1", "P2", "P3"),
        injectors=("I1", "I2"),
        matrix=((0.4, -0.1), (0.2, 0.3), (0.9, 0.05)),
        lag_months=0,
        window_end=date(2025, 9, 1),
    )
    left_path = save_lambda(
        report_of(left_influence),
        tmp_path / "left.json",
        measured_at=MEASURED_AT,
        source_run_ids=RUN_IDS,
    )
    right_path = write_legacy(tmp_path / "right.json", right_influence)
    report = compare(left_path, right_path, zero_tolerance=0.0)
    assert report.shared_producers == 2
    assert report.shared_injectors == 2
    assert report.shared_edges == 4
    assert report.lag_difference == -2
    assert report.left_provenance["measured_at"] == MEASURED_AT.isoformat()
    assert report.right_provenance["measured_at"] is None
    assert report.right_provenance["artifact_id"] is None
    assert "artifact_id" in report.right_provenance["missing_fields"]
    assert report.left_artifact_id == artifact_id(left_influence)
    assert report.right_artifact_id == artifact_id(right_influence)


def test_compare_refuses_two_disjoint_artifacts(tmp_path) -> None:
    left_path = write_legacy(
        tmp_path / "left.json", lambda_of(producers=("P1",), injectors=("I1",), matrix=((0.5,),))
    )
    right_path = write_legacy(
        tmp_path / "right.json", lambda_of(producers=("P9",), injectors=("I9",), matrix=((0.5,),))
    )
    with pytest.raises(LambdaCompareError, match="общая подматрица пуста"):
        compare(left_path, right_path, zero_tolerance=0.0)


def test_unrecorded_provenance_constant_names_every_field() -> None:
    empty = LambdaProvenance(
        artifact_id=None,
        measured_at=None,
        n_runs=None,
        source_run_ids=None,
        code_version=None,
    )
    assert set(empty.missing_fields) == set(PROVENANCE_FIELDS)
    assert not empty.is_recorded
