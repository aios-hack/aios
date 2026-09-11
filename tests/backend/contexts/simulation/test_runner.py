from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.contexts.reservoir.infrastructure.opm_deck import OpmDeckEmitter
from backend.contexts.simulation.infrastructure.runner import OpmRunner, deck_hashes
from backend.contexts.simulation.infrastructure.runner import (
    OPM_USER_ENV,
    _ITERATION_LIMIT_MARKER,
    _NOT_CONVERGED_MARKERS,
    _RECOVERABLE_MARKERS,
    _first_marker,
    _unrecovered_iteration_limit_failure,
    mount_path,
    summary_spec_hash,
)
from backend.contexts.runs.domain.run_result import RunStatus, SummarySpec
from backend.contexts.schedule.domain.schedule import Schedule, ScheduleMeta
from backend.shared.hashing import hash_schedule
from backend.contexts.schedule.domain.lossless import parse_schedule


from tests.support.backend.environment import (
    docker_unavailable_reason,
    missing_reason,
    model_z_dir,
)
from tests.support.backend.paths import DECKS_ROOT

pytestmark = [pytest.mark.slow, pytest.mark.opm]

DECKS = DECKS_ROOT

MODEL_Z = model_z_dir()

requires_model_z = pytest.mark.skipif(
    MODEL_Z is None, reason=missing_reason("Model_Z directory")
)

KEY = {
    "deck_hash": "d" * 64,
    "canonical_schedule_hash": "c" * 64,
    "summary_hash": "s" * 64,
}


requires_real_flow = pytest.mark.skipif(
    docker_unavailable_reason() is not None,
    reason=f"acceptance of task 4 requires a real OPM Flow; {docker_unavailable_reason()}",
)


def _baseline_schedule(emitter: OpmDeckEmitter) -> Schedule:
    parsed = parse_schedule((MODEL_Z / "Model_Z_sch.inc").read_bytes())
    return Schedule(
        meta=ScheduleMeta(wells=emitter.source_wells, provenance="Model_Z baseline"),
        initial_state={},
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


@requires_real_flow
def test_successful_real_flow_run_is_ok_with_existing_artifacts(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert result.status is RunStatus.OK, result.message
    assert result.deck_hash == KEY["deck_hash"]
    assert result.canonical_schedule_hash == KEY["canonical_schedule_hash"]
    assert result.summary_hash == KEY["summary_hash"]
    assert result.wallclock_seconds > 0.0
    assert result.artifacts
    assert all(Path(path).is_file() for path in result.artifacts)

    produced = {Path(path).name for path in result.artifacts}
    assert {"flow.log", "command.txt"} <= produced
    assert {"MINI.UNSMRY", "MINI.SMSPEC", "MINI.PRT"} <= produced
    assert "docker" in (tmp_path / "runs" / result.run_id / "command.txt").read_text()


@requires_real_flow
def test_non_converging_real_run_is_not_converged_without_raising(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(
        DECKS / "NOCONV.DATA",
        flow_args=("--parsing-strictness=low", "--enable-tuning=true"),
        **KEY,
    )

    assert result.status is RunStatus.NOT_CONVERGED, result.message
    assert "did not converge" in result.message
    assert any(marker in result.message for marker in _NOT_CONVERGED_MARKERS)
    assert result.artifacts


@requires_real_flow
def test_broken_deck_is_failed_without_raising(tmp_path: Path) -> None:
    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    broken = broken_dir / "BROKEN.DATA"
    broken.write_text(
        (DECKS / "MINI.DATA")
        .read_text(encoding="utf-8")
        .replace("\nDIMENS\n", "\nDIMENSXX\n"),
        encoding="utf-8",
    )

    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(broken, **KEY)

    assert result.status is RunStatus.FAILED, result.message
    assert "Unknown keyword" in result.message
    assert result.wallclock_seconds > 0.0


def test_missing_deck_is_failed_not_exception(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(tmp_path / "no-such-deck.DATA", **KEY)

    assert result.status is RunStatus.FAILED
    assert "deck not found" in result.message


def test_unavailable_docker_is_failed_not_subprocess_exception(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs", docker_binary=str(tmp_path / "no-such-docker"))
    result = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert result.status is RunStatus.FAILED
    assert "could not start" in result.message


@requires_real_flow
def test_timeout_is_failed_and_does_not_leak_a_container(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs", timeout_seconds=0.001)
    result = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert result.status is RunStatus.FAILED
    assert "did not fit into" in result.message
    assert result.run_id in result.message


@requires_real_flow
def test_two_runs_use_separate_working_directories(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    first = runner.run_data_file(DECKS / "MINI.DATA", **KEY)
    second = runner.run_data_file(DECKS / "MINI.DATA", **KEY)

    assert first.status is RunStatus.OK, first.message
    assert second.status is RunStatus.OK, second.message
    assert first.run_id != second.run_id

    first_dir = tmp_path / "runs" / first.run_id
    second_dir = tmp_path / "runs" / second.run_id
    assert first_dir.is_dir() and second_dir.is_dir()
    assert set(first.artifacts).isdisjoint(second.artifacts)
    assert all(Path(path).is_file() for path in (*first.artifacts, *second.artifacts))


def test_recoverable_linear_solver_messages_are_not_non_convergence(tmp_path: Path) -> None:

    log = tmp_path / "flow.log"
    log.write_text("\n".join(_RECOVERABLE_MARKERS) + "\n")

    assert _first_marker(log, _NOT_CONVERGED_MARKERS) is None


def test_iteration_limit_followed_by_chop_is_not_a_failure(tmp_path: Path) -> None:

    log = tmp_path / "flow.log"
    log.write_text(
        f"    Oscillating behavior detected: Relaxation set to 0.500000\n\n"
        f"Problem: {_ITERATION_LIMIT_MARKER} - Iteration limit reached\n"
        f"Timestep chopped to 10.23 days\n\n\n"
        f"Starting time step 0, stepsize 10.23 days, at day 3257/3288\n"
    )

    assert _unrecovered_iteration_limit_failure(log) is False


def test_iteration_limit_without_chop_is_a_failure(tmp_path: Path) -> None:

    log = tmp_path / "flow.log"
    log.write_text(
        f"Problem: {_ITERATION_LIMIT_MARKER} - Iteration limit reached\n"
        "\n\n\n\n\n"
        "================    End of simulation     ===============\n"
    )

    assert _unrecovered_iteration_limit_failure(log) is True


@requires_model_z
@requires_real_flow
def test_runs_emitted_model_z_deck_through_real_flow(tmp_path: Path) -> None:

    emitter = OpmDeckEmitter(MODEL_Z)
    schedule = _baseline_schedule(emitter)
    deck = emitter.emit(schedule, tmp_path / "deck")

    runner = OpmRunner(tmp_path / "runs")
    result = runner.run(
        deck,
        schedule,
        flow_args=("--parsing-strictness=low", "--enable-dry-run=true"),
    )

    assert result.status is RunStatus.OK, result.message
    assert result.canonical_schedule_hash == hash_schedule(schedule)
    assert result.deck_hash == deck_hashes(deck, schedule).deck_hash
    assert result.wallclock_seconds > 0.0
    assert all(Path(path).is_file() for path in result.artifacts)


@requires_model_z
def test_deck_hashes_bind_static_deck_schedule_and_summary_spec(tmp_path: Path) -> None:
    emitter = OpmDeckEmitter(MODEL_Z)
    schedule = _baseline_schedule(emitter)
    deck = emitter.emit(schedule, tmp_path / "deck")

    hashes = deck_hashes(deck, schedule)

    assert hashes.canonical_schedule_hash == hash_schedule(schedule)
    assert hashes.summary_hash == summary_spec_hash(SummarySpec())
    assert hashes.deck_hash != deck.content_hash_opm
    assert len(hashes.deck_hash) == 64




@pytest.mark.skipif(
    not hasattr(os, "getuid"),
    reason="uid/gid is a POSIX notion: on Windows neither the host nor the volume has them",
)
def test_container_runs_as_the_host_user_by_default(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert "--user" in command
    expected = f"{os.getuid()}:{os.getgid()}"
    assert command[command.index("--user") + 1] == expected


def test_without_posix_uid_the_image_default_user_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.delattr(os, "getgid", raising=False)
    monkeypatch.delenv(OPM_USER_ENV, raising=False)
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert "--user" not in command


def test_run_as_user_is_overridable_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPM_USER_ENV, "4242:4243")
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert command[command.index("--user") + 1] == "4242:4243"


def test_empty_override_restores_the_image_default_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.setenv(OPM_USER_ENV, "")
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA", tmp_path / "out", "opm-run-test", None
    )

    assert "--user" not in command





EXTENDED_PREFIX = "\\\\?\\"
PLAIN_DECK = "W:\\Projects\\hacks\\aios\\data\\dataset-main\\decks\\levels-0002"
PLAIN_OUT = "W:\\Projects\\hacks\\aios\\data\\dataset-main\\runs\\r1\\output"
EXTENDED_DECK = EXTENDED_PREFIX + PLAIN_DECK
EXTENDED_OUT = EXTENDED_PREFIX + PLAIN_OUT


def _mounts(command: list[str]) -> list[str]:
    return [command[index + 1] for index, arg in enumerate(command) if arg == "-v"]


def test_mount_path_strips_the_extended_length_prefix() -> None:
    assert mount_path(EXTENDED_DECK) == PLAIN_DECK


def test_mount_path_keeps_a_plain_windows_path_unchanged() -> None:
    assert mount_path(PLAIN_DECK) == PLAIN_DECK


def test_mount_path_keeps_a_posix_path_unchanged() -> None:
    posix = "/home/user/dataset-main/decks/levels-0002"
    assert mount_path(posix) == posix


def test_mount_path_restores_the_unc_form() -> None:
    assert mount_path(EXTENDED_PREFIX + "UNC\\server\\share\\decks") == (
        "\\\\server\\share\\decks"
    )


def test_volume_arguments_never_carry_the_extended_length_prefix(tmp_path: Path) -> None:
    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        Path(EXTENDED_DECK) / "X.DATA", Path(EXTENDED_OUT), "opm-run-test", None
    )

    mounts = _mounts(command)
    assert len(mounts) == 2
    for mount in mounts:
        assert EXTENDED_PREFIX not in mount, mount
    assert mounts[0] == PLAIN_DECK + ":/deck:ro"
    assert mounts[1] == PLAIN_OUT + ":/out"


def test_a_resolved_work_root_produces_a_mount_docker_can_parse(tmp_path: Path) -> None:

    runner = OpmRunner(tmp_path / "runs")
    command = runner._command(
        tmp_path / "deck" / "X.DATA",
        runner.work_root / "r1" / "output",
        "opm-run-test",
        None,
    )

    mounts = _mounts(command)
    assert len(mounts) == 2
    for mount in mounts:
        assert not mount.startswith(EXTENDED_PREFIX), mount
        assert "?" not in mount, mount
