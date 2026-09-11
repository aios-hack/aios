import json
from pathlib import Path

import pytest

from backend.contexts.constraints.application.cases import CaseError, load_case
from backend.application.runs import RunProvenance, RunRequest, RunWorkflow
from backend.contexts.runs.application.workflow import SUBMISSION_BUNDLE_FIELDS
from backend.core.contracts import SubmissionBundle, water_supply_policy
from backend.contexts.runs.infrastructure.provenance import DEFAULT_OPM_IMAGE
from backend.contexts.constraints.infrastructure.constraints_io import (
    constraints_hash,
    constraints_to_json,
)
from backend.interfaces.cli.run import (
    build_parser,
    build_provenance,
    default_case_path,
    load_run_request,
    main,
    resolve_case,
    resolve_comparison_case,
    resolve_constraints,
)
from tests.application.test_run_workflow import prepare_submittable_run, sample_schedule
from backend.shared.errors import ValidationError

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

    with pytest.raises(ValidationError) as error:
        main(["search", "--case", str(case)])

    assert "new_wells" in str(error.value)
    assert error.value.code == "runs.case_rejected"


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
                "water_reinjection_fraction_source": "assumption",
                "external_water_m3_per_day": -5.0,
                "external_water_m3_per_day_source": "organizer",
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
            "infrastructure": {
                "external_water_m3_per_day": 5000.0,
                "external_water_m3_per_day_source": "organizer",
            },
        },
    )

    constraints = load_case(case)

    assert constraints.liquid_limits == {2010: 38000.0}
    assert constraints.watercut_limits == {2012: 0.95}
    assert constraints.well_outages[0].well == "P12"
    assert constraints.infrastructure["external_water_m3_per_day"] == 5000.0

    policy = water_supply_policy(constraints)
    assert policy.enabled
    assert policy.reinjection_fraction == pytest.approx(1.0)
    assert policy.fraction_defaulted


def test_case_may_declare_the_water_source_unlimited(tmp_path) -> None:
    case = write_case(
        tmp_path / "unlimited.json",
        {
            "infrastructure": {
                "water_supply_unlimited": True,
                "water_supply_unlimited_source": "assumption",
            }
        },
    )

    policy = water_supply_policy(load_case(case))

    assert policy.unlimited
    assert not policy.enabled


def test_case_refuses_unlimited_water_together_with_an_external_volume(tmp_path) -> None:
    case = write_case(
        tmp_path / "contradiction.json",
        {
            "infrastructure": {
                "water_supply_unlimited": True,
                "water_supply_unlimited_source": "assumption",
                "external_water_m3_per_day": 5000.0,
                "external_water_m3_per_day_source": "organizer",
            }
        },
    )

    with pytest.raises(CaseError, match="water_supply_unlimited"):
        load_case(case)


def test_verify_refuses_a_case_instead_of_ignoring_it(tmp_path) -> None:
    with pytest.raises(SystemExit) as error:
        main(["verify", "--run-id", "saved", "--case", str(BASE_CASE)])

    assert "--case" in str(error.value)


def test_resolve_constraints_returns_the_loaded_case() -> None:
    assert resolve_constraints(BASE_CASE) == load_case(BASE_CASE)
    assert resolve_constraints(None) is None


def test_resolve_constraints_ignores_a_missing_default_file(tmp_path) -> None:
    assert resolve_constraints(tmp_path / "absent.json") is None


def test_a_run_prepared_with_a_case_keeps_a_copy_of_it(tmp_path) -> None:
    constraints = resolve_constraints(BASE_CASE)
    RunWorkflow(tmp_path).search(
        RunRequest("cased", sample_schedule(), constraints=constraints)
    )

    copied = tmp_path / "cased" / "inputs" / "constraints.json"
    assert copied.is_file()
    assert json.loads(copied.read_text(encoding="utf-8")) == constraints_to_json(constraints)


def test_verify_reloads_the_case_the_plan_was_found_on(tmp_path) -> None:
    constraints = resolve_constraints(BASE_CASE)
    RunWorkflow(tmp_path).search(
        RunRequest("cased", sample_schedule(), constraints=constraints)
    )

    assert load_run_request(tmp_path, "cased").constraints == constraints


def test_a_run_saved_without_a_case_reloads_without_one(tmp_path) -> None:
    RunWorkflow(tmp_path).search(RunRequest("plain", sample_schedule()))

    assert load_run_request(tmp_path, "plain").constraints is None


def test_default_case_path_follows_the_search_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AIOS_CONSTRAINTS_PATH", raising=False)
    assert default_case_path() == Path("config/competition-constraints.json")

    monkeypatch.setenv("AIOS_CONSTRAINTS_PATH", str(tmp_path / "other.json"))
    assert default_case_path() == tmp_path / "other.json"


def test_provenance_records_the_environment_and_the_case() -> None:
    class Outcome:
        provenance = {
            "model_version": "surrogate-1.4.0",
            "npv_head_version": "npv-head-2.1",
            "scenario_ood_version": "ood-3",
            "seed": "20260816",
            "search_strategy": "cma-es",
            "policy_equilibrium": "reached",
        }
        evaluations = 120
        self_consistent = True

    constraints = load_case(BASE_CASE)
    provenance = build_provenance(Outcome(), constraints)

    assert provenance.model_version == "surrogate-1.4.0"
    assert provenance.npv_head_version == "npv-head-2.1"
    assert provenance.scenario_ood_version == "ood-3"
    assert provenance.seed == "20260816"
    assert provenance.search_strategy == "cma-es"
    assert provenance.policy_equilibrium == "reached"
    assert provenance.iterations == 120
    assert provenance.self_consistent is True
    assert provenance.constraints_hash == constraints_hash(constraints)
    repository = DEFAULT_OPM_IMAGE.split(":", 1)[0]
    assert provenance.opm_image.startswith(repository)


def test_provenance_without_a_case_leaves_the_case_hash_empty() -> None:
    class Outcome:
        provenance: dict[str, str] = {}

    assert build_provenance(Outcome(), None).constraints_hash is None


def test_run_cli_exposes_the_submit_mode() -> None:
    parser = build_parser()
    assert parser.parse_args(["submit", "--run-id", "r1"]).mode == "submit"
    assert parser.parse_args(["submit", "--run-id", "r1"]).model_dir is None
    assert parser.parse_args(
        ["submit", "--run-id", "r1", "--model-dir", "m"]
    ).model_dir == Path("m")


def test_submit_without_a_run_id_is_refused() -> None:
    with pytest.raises(SystemExit, match="--run-id"):
        main(["submit"])


def test_submit_refuses_a_case_instead_of_ignoring_it() -> None:
    with pytest.raises(SystemExit, match="--case"):
        main(["submit", "--run-id", "saved", "--case", str(BASE_CASE)])


def test_submit_prints_the_package_the_claimed_number_and_every_hash(
    tmp_path, capsys
) -> None:
    _workflow, model_dir = prepare_submittable_run(tmp_path)

    assert main(
        ["submit", "--run-id", "submittable", "--runs-root", str(tmp_path / "runs"),
         "--model-dir", str(model_dir)]
    ) == 0

    printed = capsys.readouterr().out
    bundle = SubmissionBundle(
        **json.loads(
            (tmp_path / "runs" / "submittable" / "submission" / "claimed_npv.json")
            .read_text(encoding="utf-8")
        )
    )
    assert str(tmp_path / "runs" / "submittable" / "submission") in printed
    assert "well_schedule.inc" in printed
    assert f"{bundle.claimed_npv_rub:.2f}" in printed
    for name in SUBMISSION_BUNDLE_FIELDS:
        if name == "claimed_npv_rub":
            continue
        assert f"{name}: {getattr(bundle, name)}" in printed


def test_submit_through_the_cli_is_idempotent(tmp_path, capsys) -> None:
    _workflow, model_dir = prepare_submittable_run(tmp_path)
    argv = [
        "submit", "--run-id", "submittable",
        "--runs-root", str(tmp_path / "runs"), "--model-dir", str(model_dir),
    ]

    assert main(argv) == 0
    first = capsys.readouterr().out
    package = tmp_path / "runs" / "submittable" / "submission"
    names = sorted(path.name for path in package.iterdir())
    schedule_bytes = (package / "well_schedule.inc").read_bytes()

    assert main(argv) == 0
    assert capsys.readouterr().out == first
    assert sorted(path.name for path in package.iterdir()) == names
    assert (package / "well_schedule.inc").read_bytes() == schedule_bytes


def test_the_cli_reports_the_reason_a_package_was_not_built(tmp_path) -> None:
    _workflow, model_dir = prepare_submittable_run(tmp_path, "unsound", sound=False)

    with pytest.raises(SystemExit) as error:
        main(["submit", "--run-id", "unsound", "--runs-root", str(tmp_path / "runs"),
              "--model-dir", str(model_dir)])

    assert "пакет сдачи не собран" in str(error.value)
    assert "sound" in str(error.value)


def test_the_cli_writes_the_ready_status_only_after_the_package(tmp_path) -> None:
    _workflow, model_dir = prepare_submittable_run(tmp_path)
    manifest_path = tmp_path / "runs" / "submittable" / "manifest.json"

    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "verified"

    main(["submit", "--run-id", "submittable", "--runs-root", str(tmp_path / "runs"),
          "--model-dir", str(model_dir)])

    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "ready_to_submit"
    summary = tmp_path / "runs" / "submittable" / "ui" / "run.json"
    assert json.loads(summary.read_text(encoding="utf-8"))["status"] == "ready_to_submit"


def test_a_reloaded_run_keeps_the_provenance_the_search_recorded(tmp_path) -> None:
    provenance = RunProvenance(
        constraints_hash="b" * 64,
        opm_image=DEFAULT_OPM_IMAGE,
        git_commit="e" * 40,
        seed="20260816",
    )
    RunWorkflow(tmp_path).search(
        RunRequest("traced", sample_schedule(), provenance=provenance)
    )

    assert load_run_request(tmp_path, "traced").provenance == provenance


def test_a_run_without_a_manifest_reloads_with_empty_provenance(tmp_path) -> None:
    RunWorkflow(tmp_path).search(RunRequest("plain", sample_schedule()))
    (tmp_path / "plain" / "manifest.json").unlink()

    assert load_run_request(tmp_path, "plain").provenance == RunProvenance()


def test_compare_is_one_of_the_workflow_modes() -> None:
    parser = build_parser()
    assert parser.parse_args(["compare", "--run-id", "r1"]).mode == "compare"


def test_compare_without_a_run_id_is_refused() -> None:
    with pytest.raises(SystemExit, match="--run-id"):
        main(["compare"])


def test_compare_refuses_a_case_that_differs_from_the_case_of_the_run(
    tmp_path,
) -> None:
    runs_root = tmp_path / "runs"
    saved = load_case(BASE_CASE)
    RunWorkflow(runs_root).search(
        RunRequest("compared", sample_schedule(), constraints=saved)
    )
    other = write_case(
        tmp_path / "other.json",
        {**constraints_to_json(saved), "liquid_limits": {"2010": 1.0}},
    )

    with pytest.raises(SystemExit) as error:
        resolve_comparison_case(runs_root, "compared", other)

    message = str(error.value)
    assert "расходится с кейсом прогона" in message
    assert constraints_hash(saved) in message


def test_compare_accepts_the_case_that_matches_the_run(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    saved = load_case(BASE_CASE)
    RunWorkflow(runs_root).search(
        RunRequest("compared", sample_schedule(), constraints=saved)
    )

    path, constraints = resolve_comparison_case(runs_root, "compared", BASE_CASE)

    assert path == BASE_CASE
    assert constraints_hash(constraints) == constraints_hash(saved)


def test_compare_falls_back_to_the_case_stored_with_the_run(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    saved = load_case(BASE_CASE)
    RunWorkflow(runs_root).search(
        RunRequest("compared", sample_schedule(), constraints=saved)
    )
    missing = tmp_path / "absent.json"

    path, constraints = resolve_comparison_case(runs_root, "compared", missing)

    assert path == runs_root / "compared" / "inputs" / "constraints.json"
    assert constraints_hash(constraints) == constraints_hash(saved)


def test_compare_without_any_case_at_all_is_refused(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    RunWorkflow(runs_root).search(RunRequest("bare", sample_schedule()))

    with pytest.raises(SystemExit) as error:
        resolve_comparison_case(runs_root, "bare", tmp_path / "absent.json")

    assert "кейс не найден" in str(error.value)
