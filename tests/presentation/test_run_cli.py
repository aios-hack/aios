from backend.application.runs import RunRequest, RunWorkflow
from backend.presentation.cli.run import build_parser, load_run_request
from tests.application.test_run_workflow import sample_schedule


def test_run_cli_exposes_the_three_workflow_modes() -> None:
    parser = build_parser()
    assert parser.parse_args(["search"]).mode == "search"
    assert parser.parse_args(["verify"]).mode == "verify"
    assert parser.parse_args(["full"]).mode == "full"


def test_verify_reloads_the_exact_schedule_of_a_previous_run(tmp_path) -> None:
    request = RunRequest("saved", sample_schedule(), predicted_npv=12.5)
    RunWorkflow(tmp_path).search(request)

    loaded = load_run_request(tmp_path, "saved")

    assert loaded.run_id == request.run_id
    assert loaded.predicted_npv == request.predicted_npv
    assert loaded.schedule == request.schedule
