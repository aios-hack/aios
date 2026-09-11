from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contexts.optimization.infrastructure.artifacts import (
    CONSERVATIVE_OOD_THRESHOLD,
    RuntimeArtifactError,
    resolve_ood_threshold,
)
from backend.contexts.optimization.application.search_use_case import (
    SearchRunError,
    _ood_threshold_decision,
    _soft_penalty_enabled,
    _soft_penalty_rate,
    incumbent_gate_passed,
)
from backend.contexts.optimization.application.environment import (
    ScheduleSearchError,
    SearchEnvironment,
    apply_ood_penalty,
    ood_penalty_factor,
)
from tools.ood_calibration import (
    FORMAT,
    CalibrationPoint,
    OodCalibrationError,
    calibrate,
    choose_threshold,
    collect_points,
    collect_run_point,
    load_calibration,
    write_artifact,
)
from backend.contexts.optimization.application import environment as _src_environment
from tests.support.backend.paths import OUT_ROOT

REAL_RUNS = OUT_ROOT / "web-runs"


def _run_dir(root: Path, run_id: str, predicted: float, verified: float, score: float | None) -> Path:
    directory = root / run_id
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "schedule_hash": f"hash-{run_id}",
                "predicted_npv": predicted,
                "verified_npv": verified,
            }
        ),
        encoding="utf-8",
    )
    candidate: dict[str, object] = {"feasible": True, "npv_predicted": predicted}
    if score is not None:
        candidate["ood_score"] = score
    (directory / "diagnostics.json").write_text(
        json.dumps({"ood_threshold": 0.0, "evaluations": [candidate]}),
        encoding="utf-8",
    )
    return directory


def test_tool_refuses_to_work_on_empty_data(tmp_path: Path) -> None:
    empty = tmp_path / "web-runs"
    empty.mkdir()

    with pytest.raises(OodCalibrationError, match="not a single forecast-versus-fact pair"):
        calibrate([empty], 0.01)


def test_tool_refuses_when_run_has_no_opm_fact(tmp_path: Path) -> None:
    root = tmp_path / "web-runs"
    directory = root / "web-unverified"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({"run_id": "web-unverified", "predicted_npv": 1.0, "verified_npv": None}),
        encoding="utf-8",
    )
    (directory / "diagnostics.json").write_text(
        json.dumps({"ood_threshold": 0.0, "evaluations": []}), encoding="utf-8"
    )

    with pytest.raises(OodCalibrationError, match="not a single forecast-versus-fact pair"):
        calibrate([root], 0.01)


def test_single_point_is_reported_as_unreliable_not_as_a_curve(tmp_path: Path) -> None:
    root = tmp_path / "web-runs"
    _run_dir(root, "web-one", 100.0, 101.0, 0.0)

    result = calibrate([root], 0.05)

    assert result.point_count == 1
    assert result.curve_is_reliable is False
    assert result.threshold_origin.endswith("insufficient-points")


def test_point_count_in_artifact_matches_the_measured_pairs(tmp_path: Path) -> None:
    root = tmp_path / "web-runs"
    _run_dir(root, "web-a", 100.0, 101.0, 0.0)
    _run_dir(root, "web-b", 200.0, 204.0, 0.5)
    _run_dir(root, "web-c", 300.0, 330.0, 4.0)

    result = calibrate([root], 0.05)
    destination = write_artifact(result, tmp_path / "ood-calibration.json")
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["format"] == FORMAT
    assert payload["point_count"] == 3
    assert len(payload["points"]) == payload["point_count"]
    assert result.curve_is_reliable is True
    assert pytest.approx(payload["threshold"]) == 0.5
    assert load_calibration(destination).point_count == 3


def test_threshold_is_the_largest_score_still_inside_tolerated_error(tmp_path: Path) -> None:
    points = [
        CalibrationPoint("a", "h", 0.0, 100.0, 100.5, 0.005, "s"),
        CalibrationPoint("b", "h", 1.5, 100.0, 101.0, 0.01, "s"),
        CalibrationPoint("c", "h", 3.0, 100.0, 120.0, 0.2, "s"),
    ]

    result = choose_threshold(points, [], 0.02)

    assert result.threshold == 1.5
    assert result.point_count == 3


def test_tool_refuses_when_no_point_meets_the_tolerated_error() -> None:
    points = [CalibrationPoint("a", "h", 0.0, 100.0, 150.0, 0.5, "s")]

    with pytest.raises(OodCalibrationError, match="fits into the tolerated"):
        choose_threshold(points, [], 0.01)


@pytest.mark.skipif(not REAL_RUNS.is_dir(), reason="the runs directory is unavailable")
def test_real_runs_give_the_pairs_the_report_claims() -> None:
    points, rejected = collect_points([REAL_RUNS])

    confirmed = [
        directory
        for directory in sorted(REAL_RUNS.iterdir())
        if directory.is_dir()
        and (directory / "manifest.json").is_file()
        and (directory / "diagnostics.json").is_file()
    ]
    assert len(points) == len(confirmed)
    assert len(points) >= 1
    for point in points:
        assert point.relative_error >= 0.0
        assert point.npv_verified != 0.0
    assert rejected


@pytest.mark.skipif(not REAL_RUNS.is_dir(), reason="the runs directory is unavailable")
def test_run_without_opm_fact_contributes_no_point() -> None:
    for directory in sorted(REAL_RUNS.iterdir()):
        if not directory.is_dir() or (directory / "manifest.json").is_file():
            continue
        point, _ = collect_run_point(directory)
        assert point is None


def test_threshold_comes_from_the_calibration_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "ood-calibration.json"
    artifact.write_text(
        json.dumps(
            {
                "format": FORMAT,
                "threshold": 1.25,
                "threshold_origin": "measured-error-curve",
                "tolerated_relative_error": 0.01,
                "point_count": 1,
                "curve_is_reliable": True,
                "points": [
                    {
                        "run_id": "a",
                        "ood_score": 1.25,
                        "npv_predicted": 1.0,
                        "npv_verified": 1.0,
                        "relative_error": 0.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    decision = resolve_ood_threshold({"AIOS_OOD_CALIBRATION_PATH": str(artifact)})

    assert decision.value == 1.25
    assert decision.calibrated is True
    assert decision.origin == "calibration-artifact"
    assert decision.calibration_path == artifact
    assert decision.as_provenance()["ood_threshold_source"] == str(artifact)


def test_environment_variable_overrides_the_artifact_and_shows_up_in_provenance(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "ood-calibration.json"
    artifact.write_text(
        json.dumps(
            {
                "format": FORMAT,
                "threshold": 1.25,
                "tolerated_relative_error": 0.01,
                "point_count": 1,
                "points": [
                    {
                        "run_id": "a",
                        "ood_score": 1.25,
                        "npv_predicted": 1.0,
                        "npv_verified": 1.0,
                        "relative_error": 0.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    decision = resolve_ood_threshold(
        {"AIOS_OOD_CALIBRATION_PATH": str(artifact), "AIOS_OOD_THRESHOLD": "7.5"}
    )
    provenance = decision.as_provenance()

    assert decision.value == 7.5
    assert decision.origin == "environment-override"
    assert decision.calibrated is False
    assert provenance["ood_threshold"] == repr(7.5)
    assert provenance["ood_threshold_origin"] == "environment-override"
    assert provenance["ood_threshold_calibrated"] == "false"
    assert "AIOS_OOD_THRESHOLD" in provenance["ood_threshold_detail"]


def test_missing_artifact_gives_the_conservative_threshold_marked_uncalibrated(
    tmp_path: Path,
) -> None:
    decision = resolve_ood_threshold({"AIOS_PROJECT_ROOT": str(tmp_path)})
    provenance = decision.as_provenance()

    assert decision.value == CONSERVATIVE_OOD_THRESHOLD
    assert decision.calibrated is False
    assert decision.origin == "uncalibrated-conservative-default"
    assert decision.calibration_path is None
    assert provenance["ood_threshold_calibrated"] == "false"
    assert "NOT CALIBRATED" in provenance["ood_threshold_detail"]


def test_configured_calibration_path_that_is_missing_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeArtifactError, match="points at a missing"):
        resolve_ood_threshold({"AIOS_OOD_CALIBRATION_PATH": str(tmp_path / "absent.json")})


def test_calibration_without_a_single_point_does_not_set_a_threshold(tmp_path: Path) -> None:
    artifact = tmp_path / "ood-calibration.json"
    artifact.write_text(
        json.dumps({"format": FORMAT, "threshold": 9.0, "point_count": 0, "points": []}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeArtifactError, match="without a single measured point"):
        resolve_ood_threshold({"AIOS_OOD_CALIBRATION_PATH": str(artifact)})


def test_non_numeric_override_is_an_error_not_a_silent_zero() -> None:
    with pytest.raises(RuntimeArtifactError, match="is given as a number"):
        resolve_ood_threshold({"AIOS_OOD_THRESHOLD": "almost zero"})


def _calibration_file(path: Path, threshold: float, reliable: bool) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": FORMAT,
                "threshold": threshold,
                "tolerated_relative_error": 0.01,
                "point_count": 2,
                "curve_is_reliable": reliable,
                "points": [
                    {
                        "run_id": "a",
                        "ood_score": threshold,
                        "npv_predicted": 1.0,
                        "npv_verified": 1.0,
                        "relative_error": 0.0,
                    },
                    {
                        "run_id": "b",
                        "ood_score": 0.0,
                        "npv_predicted": 1.0,
                        "npv_verified": 1.0,
                        "relative_error": 0.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_run_reads_tau_from_the_artifact_and_says_so_in_provenance(
    tmp_path: Path,
) -> None:
    artifact = _calibration_file(tmp_path / "ood-calibration.json", 2.5, True)

    decision = _ood_threshold_decision({"AIOS_OOD_CALIBRATION_PATH": str(artifact)})
    provenance = decision.as_provenance()

    assert decision.value == 2.5
    assert provenance["ood_threshold"] == repr(2.5)
    assert provenance["ood_threshold_origin"] == "calibration-artifact"
    assert provenance["ood_threshold_calibrated"] == "true"
    assert provenance["ood_threshold_source"] == str(artifact)
    assert provenance["ood_threshold_point_count"] == "2"


def test_the_run_marks_an_unreliable_curve_in_provenance(tmp_path: Path) -> None:
    artifact = _calibration_file(tmp_path / "ood-calibration.json", 2.5, False)

    provenance = _ood_threshold_decision(
        {"AIOS_OOD_CALIBRATION_PATH": str(artifact)}
    ).as_provenance()

    assert provenance["ood_threshold_origin"].endswith("insufficient-points")
    assert "too few points" in provenance["ood_threshold_detail"]


def test_the_run_lets_the_environment_variable_override_and_records_it(
    tmp_path: Path,
) -> None:
    artifact = _calibration_file(tmp_path / "ood-calibration.json", 2.5, True)

    provenance = _ood_threshold_decision(
        {"AIOS_OOD_CALIBRATION_PATH": str(artifact), "AIOS_OOD_THRESHOLD": "9.5"}
    ).as_provenance()

    assert provenance["ood_threshold"] == repr(9.5)
    assert provenance["ood_threshold_origin"] == "environment-override"
    assert provenance["ood_threshold_calibrated"] == "false"


def test_the_run_falls_back_to_the_conservative_threshold_marked_uncalibrated(
    tmp_path: Path,
) -> None:
    provenance = _ood_threshold_decision(
        {"AIOS_PROJECT_ROOT": str(tmp_path)}
    ).as_provenance()

    assert provenance["ood_threshold"] == repr(0.0)
    assert provenance["ood_threshold_origin"] == "uncalibrated-conservative-default"
    assert provenance["ood_threshold_calibrated"] == "false"
    assert provenance["ood_threshold_source"] == "none"
    assert "NOT CALIBRATED" in provenance["ood_threshold_detail"]


def test_the_run_refuses_a_calibration_without_a_measured_point(tmp_path: Path) -> None:
    artifact = tmp_path / "ood-calibration.json"
    artifact.write_text(
        json.dumps({"format": FORMAT, "threshold": 3.0, "point_count": 0, "points": []}),
        encoding="utf-8",
    )

    with pytest.raises(SearchRunError, match="without a single measured point"):
        _ood_threshold_decision({"AIOS_OOD_CALIBRATION_PATH": str(artifact)})


def test_soft_penalty_is_off_by_default_and_the_gate_is_bit_for_bit_unchanged() -> None:
    assert _soft_penalty_enabled({}) is False

    gate = dict(
        static_violations=0,
        dynamic_blocking_violations=0,
        ood_score=5.0,
        ood_threshold=0.0,
        physics_admissible=True,
    )
    assert incumbent_gate_passed(**gate) is False
    assert incumbent_gate_passed(**gate, ood_soft_penalty=False) is False
    assert (
        incumbent_gate_passed(
            static_violations=0,
            dynamic_blocking_violations=0,
            ood_score=0.0,
            ood_threshold=0.0,
            physics_admissible=True,
        )
        is True
    )


def test_soft_penalty_keeps_an_out_of_domain_candidate_but_lowers_its_npv() -> None:
    assert _soft_penalty_enabled({"AIOS_OOD_SOFT_PENALTY": "1"}) is True

    assert (
        incumbent_gate_passed(
            static_violations=0,
            dynamic_blocking_violations=0,
            ood_score=5.0,
            ood_threshold=0.0,
            physics_admissible=True,
            ood_soft_penalty=True,
        )
        is True
    )

    npv = 1.0e10
    penalized = apply_ood_penalty(npv, 5.0, 1.0)
    assert penalized < npv
    assert penalized > 0.0
    assert apply_ood_penalty(npv, 0.0, 1.0) == npv


def test_penalty_grows_with_the_ood_score() -> None:
    npv = 1.0e10
    mild = apply_ood_penalty(npv, 1.0, 0.5)
    harsh = apply_ood_penalty(npv, 10.0, 0.5)

    assert harsh < mild < npv
    assert ood_penalty_factor(0.0, 1.0) == 1.0
    assert 0.0 < ood_penalty_factor(3.0, 1.0) < 1.0


def test_soft_penalty_does_not_flip_the_sign_of_a_negative_npv() -> None:
    penalized = apply_ood_penalty(-1.0e9, 4.0, 1.0)

    assert penalized < -1.0e9


def test_penalty_refuses_a_non_finite_npv_instead_of_inventing_one() -> None:
    with pytest.raises(ScheduleSearchError, match="is not finite"):
        apply_ood_penalty(float("inf"), 1.0, 1.0)

    with pytest.raises(ScheduleSearchError, match="is not finite or is negative"):
        ood_penalty_factor(-1.0, 1.0)

    with pytest.raises(ScheduleSearchError, match="is not finite or is negative"):
        ood_penalty_factor(1.0, -1.0)


def test_the_environment_defaults_to_the_hard_rejection() -> None:
    fields = SearchEnvironment.__dataclass_fields__

    assert fields["ood_soft_penalty"].default is False
    assert fields["ood_penalty_per_unit"].default == 0.0


def test_enabling_the_penalty_without_a_rate_is_refused_not_silently_disarmed() -> None:
    source = Path(_src_environment.__file__).read_text(encoding="utf-8")

    assert "if ood_soft_penalty and ood_penalty_per_unit <= 0.0:" in source
    assert "removing the guard entirely" in source


def test_the_evaluator_only_penalizes_when_the_option_is_on() -> None:
    source = Path(_src_environment.__file__).read_text(encoding="utf-8")

    assert "if env.ood_soft_penalty:" in source
    assert "_enforce_scenario_ood(model_input, env.model, env.scenario_ood)" in source
    assert "_enforce_ood_threshold(scored.ood, env.ood_threshold)" in source
    assert "if env.ood_soft_penalty and penalty_excess > 0.0:" in source
    assert "unpenalized_blended" in source
    assert "ood_penalty_excess" in source


def test_penalty_rate_must_be_positive_when_the_option_is_on() -> None:
    assert _soft_penalty_rate({}) == 1.0
    assert _soft_penalty_rate({"AIOS_OOD_PENALTY_PER_UNIT": "0.25"}) == 0.25

    with pytest.raises(SearchRunError, match="must be finite"):
        _soft_penalty_rate({"AIOS_OOD_PENALTY_PER_UNIT": "0"})

    with pytest.raises(SearchRunError, match="is given as a number"):
        _soft_penalty_rate({"AIOS_OOD_PENALTY_PER_UNIT": "almost"})

    with pytest.raises(SearchRunError, match="a boolean value"):
        _soft_penalty_enabled({"AIOS_OOD_SOFT_PENALTY": "maybe"})
