from aios_backend.presentation.cli.run import build_parser


def test_run_cli_exposes_the_three_workflow_modes() -> None:
    parser = build_parser()
    assert parser.parse_args(["search"]).mode == "search"
    assert parser.parse_args(["verify"]).mode == "verify"
    assert parser.parse_args(["full"]).mode == "full"
