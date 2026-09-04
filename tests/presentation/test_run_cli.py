import json
from pathlib import Path

import pytest

from backend.application.cases import CaseError, load_case
from backend.application.runs import RunRequest, RunWorkflow
from backend.presentation.cli.run import build_parser, load_run_request, main, resolve_case
from tests.application.test_run_workflow import sample_schedule

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_CASE = REPO_ROOT / "config" / "cases" / "base.json"
DEFAULT_CONSTRAINTS = REPO_ROOT / "config" / "competition-constraints.json"


def write_case(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_run_cli_exposes_the_three_workflow_modes() -> None:
    parser = build_parser()
    assert parser.parse_args(["search"]).mode == "search"
    assert parser.parse_args(["verify"]).mode == "verify"
    assert parser.parse_args(["full"]).mode == "full"


def test_run_cli_defaults_to_the_out_root_runs_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AIOS_OUT_DIR", str(tmp_path / "out"))
    assert build_parser().parse_args(["search"]).runs_root == (tmp_path / "out" / "runs").resolve()


def test_verify_reloads_the_exact_schedule_of_a_previous_run(tmp_path) -> None:
    request = RunRequest("saved", sample_schedule(), predicted_npv=12.5)
    RunWorkflow(tmp_path).search(request)

    loaded = load_run_request(tmp_path, "saved")

    assert loaded.run_id == request.run_id
    assert loaded.predicted_npv == request.predicted_npv
    assert loaded.schedule == request.schedule


def test_case_argument_is_parsed_and_defaults_to_none() -> None:
    parser = build_parser()
    assert parser.parse_args(["search"]).case is None
    assert parser.parse_args(["full", "--case", str(BASE_CASE)]).case == BASE_CASE


def test_base_case_is_equivalent_to_the_default_configuration() -> None:
    assert load_case(BASE_CASE) == load_case(DEFAULT_CONSTRAINTS)


def test_resolve_case_reads_the_file_and_returns_its_path() -> None:
    assert resolve_case(None) is None
    assert resolve_case(BASE_CASE) == BASE_CASE


def test_base_case_declares_the_compensation_corridor_and_external_water() -> None:
    infrastructure = load_case(BASE_CASE).infrastructure

    assert infrastructure["compensation_min"] == 0.85
    assert infrastructure["compensation_max"] == 1.15
    assert infrastructure["external_water_m3_per_day"] == 0.0


def test_unknown_top_level_field_is_refused_and_named(tmp_path) -> None:
    case = write_case(tmp_path / "case.json", {"gas_limits": {"2010": 1.0}})

    with pytest.raises(CaseError, match="gas_limits"):
        load_case(case)


def test_unknown_infrastructure_key_is_refused_and_named(tmp_path) -> None:
    case = write_case(
        tmp_path / "case.json", {"infrastructure": {"compensaton_min": 0.9}}
    )

    with pytest.raises(CaseError, match="infrastructure.compensaton_min"):
        load_case(case)


def test_new_wells_is_refused_with_a_stated_reason(tmp_path) -> None:
    case = write_case(
        tmp_path / "case.json", {"new_wells": [{"name": "W-100", "x": 1, "y": 2}]}
    )

    with pytest.raises(CaseError) as error:
        load_case(case)

    message = str(error.value)
    assert "new_wells" in message
    assert "не поддерживается" in message
    assert "Model_Z" in message


def test_case_cli_refuses_new_wells_before_running_the_search(tmp_path) -> None:
    case = write_case(tmp_path / "case.json", {"new_wells": [{"name": "W-100"}]})

    with pytest.raises(SystemExit) as error:
        main(["search", "--case", str(case)])

    assert "new_wells" in str(error.value)


def test_missing_case_file_is_refused_with_its_path(tmp_path) -> None:
    missing = tmp_path / "absent.json"

    with pytest.raises(CaseError, match="не найден"):
        load_case(missing)


def test_malformed_json_is_refused_with_position(tmp_path) -> None:
    broken = tmp_path / "case.json"
    broken.write_text('{"injection_limits": }', encoding="utf-8")

    with pytest.raises(CaseError, match="не разбирается как JSON"):
        load_case(broken)


def test_half_a_compensation_corridor_is_refused_at_load_time(tmp_path) -> None:
    case = write_case(
        tmp_path / "case.json", {"infrastructure": {"compensation_min": 0.9}}
    )

    with pytest.raises(CaseError, match="compensation_max"):
        load_case(case)


def test_negative_external_water_is_refused_at_load_time(tmp_path) -> None:
    case = write_case(
        tmp_path / "case.json",
        {
            "infrastructure": {
                "water_reinjection_fraction": 1.0,
                "external_water_m3_per_day": -5.0,
            }
        },
    )

    with pytest.raises(CaseError, match="external_water_m3_per_day"):
        load_case(case)


def test_case_with_outages_and_limits_is_accepted(tmp_path) -> None:
    case = write_case(
        tmp_path / "case.json",
        {
            "liquid_limits": {"2010": 38000.0},
            "watercut_limits": {"2012": 0.95},
            "well_outages": [
                {"well": "P12", "control_step_from": 48, "control_step_to": 51}
            ],
            "infrastructure": {"external_water_m3_per_day": 5000.0},
        },
    )

    constraints = load_case(case)

    assert constraints.liquid_limits == {2010: 38000.0}
    assert constraints.watercut_limits == {2012: 0.95}
    assert constraints.well_outages[0].well == "P12"
    assert constraints.infrastructure["external_water_m3_per_day"] == 5000.0


def test_verify_refuses_a_case_instead_of_ignoring_it(tmp_path) -> None:
    with pytest.raises(SystemExit) as error:
        main(["verify", "--run-id", "saved", "--case", str(BASE_CASE)])

    assert "--case" in str(error.value)
