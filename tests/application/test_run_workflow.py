from dataclasses import dataclass

from aios_backend.application.runs import RunRequest, RunWorkflow, WorkflowStatus
from aios_backend.core.contracts import (
    Availability,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)


@dataclass(frozen=True)
class FakeVerification:
    sound: bool
    npv_methodology: float | None


def sample_schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("W1",)),
        initial_state={
            "W1": WellState(Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, 10.0)
        },
        fixed_deck_events=(),
        control_events=(),
    )


def test_verified_run_has_complete_layout_and_ready_status(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    request = RunRequest("good-plan", sample_schedule(), predicted_npv=12.5)

    result = workflow.verify(request, lambda _schedule, _opm: FakeVerification(True, 11.0))

    assert result.status is WorkflowStatus.READY_TO_SUBMIT
    assert result.sound is True
    run_dir = tmp_path / "runs" / "good-plan"
    assert (run_dir / "manifest.json").is_file()
    assert all((run_dir / part).is_dir() for part in ("inputs", "schedule", "prediction", "opm", "validation", "economics", "ui"))


def test_unsound_opm_result_is_rejected(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")

    result = workflow.verify(
        RunRequest("bad-plan", sample_schedule()),
        lambda _schedule, _opm: FakeVerification(False, 10.0),
    )

    assert result.status is WorkflowStatus.REJECTED
    assert result.sound is False
