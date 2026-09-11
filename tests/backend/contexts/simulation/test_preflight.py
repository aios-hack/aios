from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.core.contracts import RunResult, RunStatus
from backend.contexts.simulation.infrastructure import preflight as preflight_module
from backend.contexts.simulation.infrastructure import runner as runner_module
from backend.contexts.simulation.infrastructure.cache import RunCache
from backend.contexts.simulation.infrastructure.dataset import (
    ALWAYS_RETAINED,
    COMPACTED_ON_REQUEST,
    SCHEDULES_DIR,
    DatasetError,
    DatasetGenerator,
)
from backend.contexts.reservoir.infrastructure.opm_deck import EmittedOpmDeck
from backend.contexts.simulation.infrastructure.preflight import (
    DockerPreflightError,
    PreflightProblem,
    docker_preflight,
    ensure_docker_ready,
    resolve_image_reference,
)
from backend.contexts.simulation.infrastructure.runner import OpmRunner

IMAGE = "openporousmedia/opmreleases:latest"
DIGEST = "openporousmedia/opmreleases@sha256:" + "a" * 64

REPO_ROOT = Path(__file__).resolve().parents[4]


def _completed(
    args: list[str], returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def _fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    *,
    info: subprocess.CompletedProcess[str] | Exception | None = None,
    inspect: subprocess.CompletedProcess[str] | Exception | None = None,
    binary: str | None = "/usr/bin/docker",
) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        preflight_module.shutil, "which", lambda name: binary
    )

    def run(command, *, timeout_seconds):  # type: ignore[no-untyped-def]
        calls.append(list(command))
        outcome = inspect if "inspect" in list(command) else info
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            return _completed(list(command), 0, stdout="27.0.0\n")
        return outcome

    monkeypatch.setattr(preflight_module, "run_docker", run)
    return calls


class _NoDocker:
    def __init__(self, run) -> None:  # type: ignore[no-untyped-def]
        self.run = run
        self.PIPE = subprocess.PIPE
        self.STDOUT = subprocess.STDOUT
        self.DEVNULL = subprocess.DEVNULL
        self.TimeoutExpired = subprocess.TimeoutExpired


def _inspect_ok(digests: list[str]) -> subprocess.CompletedProcess[str]:
    return _completed(
        ["docker", "image", "inspect"],
        0,
        stdout=json.dumps({"Id": "sha256:" + "b" * 64, "RepoDigests": digests}),
    )


def test_preflight_reports_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(monkeypatch, binary=None)
    report = docker_preflight(image=IMAGE)
    assert report.problem is PreflightProblem.BINARY_MISSING
    assert not report.ok
    assert "PATH" in report.message


def test_preflight_distinguishes_stopped_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(
        monkeypatch,
        info=_completed(
            ["docker", "info"],
            1,
            stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
            "Is the docker daemon running?",
        ),
    )
    report = docker_preflight(image=IMAGE)
    assert report.problem is PreflightProblem.DAEMON_DOWN
    assert "Демон Docker не отвечает" in report.message


def test_preflight_distinguishes_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_docker(
        monkeypatch,
        info=_completed(
            ["docker", "info"],
            1,
            stderr="Got permission denied while trying to connect to the Docker "
            "daemon socket at unix:///var/run/docker.sock",
        ),
    )
    report = docker_preflight(image=IMAGE)
    assert report.problem is PreflightProblem.PERMISSION_DENIED
    assert "Нет прав" in report.message


def test_preflight_distinguishes_missing_image(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(
        monkeypatch,
        inspect=_completed(
            ["docker", "image", "inspect"],
            1,
            stderr=f"Error: No such image: {IMAGE}",
        ),
    )
    report = docker_preflight(image=IMAGE)
    assert report.problem is PreflightProblem.IMAGE_MISSING
    assert "docker pull" in report.message
    assert report.digest is None


def test_three_situations_have_three_distinct_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    for outcome in (
        {"info": _completed(["docker"], 1, stderr="Is the docker daemon running?")},
        {"info": _completed(["docker"], 1, stderr="Got permission denied")},
        {"inspect": _completed(["docker"], 1, stderr="No such image")},
    ):
        _fake_docker(monkeypatch, **outcome)  # type: ignore[arg-type]
        messages.append(docker_preflight(image=IMAGE).message)
    assert len(set(messages)) == 3


def test_preflight_ok_returns_repo_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(monkeypatch, inspect=_inspect_ok([DIGEST]))
    report = docker_preflight(image=IMAGE)
    assert report.ok
    assert report.problem is PreflightProblem.OK
    assert report.digest == DIGEST


def test_ensure_docker_ready_raises_with_the_same_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_docker(
        monkeypatch,
        info=_completed(["docker"], 1, stderr="Is the docker daemon running?"),
    )
    expected = docker_preflight(image=IMAGE).message
    with pytest.raises(DockerPreflightError) as error:
        ensure_docker_ready(image=IMAGE)
    assert str(error.value) == expected
    assert error.value.problem is PreflightProblem.DAEMON_DOWN


def test_image_reference_pins_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(monkeypatch, inspect=_inspect_ok([DIGEST]))
    reference = resolve_image_reference(image=IMAGE)
    assert reference.pinned
    assert reference.digest == DIGEST
    assert reference.image == DIGEST
    assert "sha256:" in reference.image


def test_image_reference_marks_tag_when_digest_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_docker(
        monkeypatch,
        inspect=_completed(["docker"], 1, stderr="No such image"),
    )
    reference = resolve_image_reference(image=IMAGE)
    assert not reference.pinned
    assert reference.digest is None
    assert reference.image.startswith(IMAGE)
    assert "тег" in reference.image
    assert "sha256:" not in reference.image


def test_image_reference_marks_tag_when_repo_digests_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_docker(monkeypatch, inspect=_inspect_ok([]))
    reference = resolve_image_reference(image=IMAGE)
    assert not reference.pinned
    assert reference.digest is None
    assert "тег" in reference.image


def test_runner_refuses_to_start_flow_without_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_docker(
        monkeypatch,
        info=_completed(["docker"], 1, stderr="Is the docker daemon running?"),
    )
    started: list[list[str]] = []

    def never(command, **kwargs):  # type: ignore[no-untyped-def]
        started.append(list(command))
        raise AssertionError("flow не должен запускаться при отказе preflight")

    monkeypatch.setattr(runner_module, "subprocess", _NoDocker(never))
    runner = OpmRunner(tmp_path / "runs", image=IMAGE)
    result = runner.run_data_file(
        tmp_path / "missing.DATA",
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
        run_id="preflight-run",
    )
    assert result.status is RunStatus.FAILED
    assert "Демон Docker не отвечает" in result.message
    assert started == []


def test_every_consumer_uses_the_shared_preflight() -> None:
    consumers = (
        REPO_ROOT / "backend" / "interfaces" / "cli" / "web_run_worker.py",
        REPO_ROOT / "backend" / "interfaces" / "cli" / "run.py",
        REPO_ROOT / "backend" / "contexts" / "simulation" / "infrastructure" / "runner.py",
    )
    for path in consumers:
        source = path.read_text(encoding="utf-8")
        assert "preflight import" in source, path
        assert "'docker', 'info'" not in source, path
        assert '"docker", "info"' not in source, path
        assert "docker info" not in source, path


def test_run_cli_writes_image_reference_not_bare_tag() -> None:
    source = (REPO_ROOT / "backend" / "interfaces" / "cli" / "run.py").read_text(
        encoding="utf-8"
    )
    assert "opm_image=resolve_image_reference().image" in source
    assert "opm_image=opm_image()" not in source


def test_cache_misses_when_a_stored_artifact_disappeared(tmp_path: Path) -> None:
    cache = RunCache(tmp_path / "cache")
    artifact = tmp_path / "output" / "MODEL_Z.UNSMRY"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"summary")
    result = RunResult(
        run_id="run-1",
        status=RunStatus.OK,
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
        artifacts=(str(artifact),),
        wallclock_seconds=1.0,
        message="OK",
    )
    cache.store(result)
    assert cache.lookup("d" * 64, "c" * 64, "s" * 64) == result

    artifact.unlink()

    assert cache.lookup("d" * 64, "c" * 64, "s" * 64) is None


def _compaction_fixture(tmp_path: Path) -> tuple[DatasetGenerator, RunResult, EmittedOpmDeck, Path, Path]:
    dataset_root = tmp_path / "dataset"
    run_root = dataset_root / "runs" / "run-1"
    output = run_root / "output"
    output.mkdir(parents=True)
    smspec = output / "MODEL_Z.SMSPEC"
    unsmry = output / "MODEL_Z.UNSMRY"
    heavy = output / "MODEL_Z.EGRID"
    for path, content in ((smspec, b"spec"), (unsmry, b"summary"), (heavy, b"heavy")):
        path.write_bytes(content)

    deck_root = dataset_root / "decks" / "scenario-1"
    deck_root.mkdir(parents=True)
    data_file = deck_root / "Model_Z.data"
    schedule_file = deck_root / "Model_Z_sch.inc"
    summary_file = deck_root / "Model_Z_summary.inc"
    data_file.write_bytes(b"deck")
    schedule_file.write_bytes(b"WCONPROD\n/\n")
    summary_file.write_bytes(b"summary")

    generator = DatasetGenerator(
        tmp_path / "model",
        dataset_root,
        emitter=object(),  # type: ignore[arg-type]
    )
    result = RunResult(
        run_id="run-1",
        status=RunStatus.OK,
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
        artifacts=tuple(str(path) for path in (smspec, unsmry, heavy)),
        wallclock_seconds=1.0,
        message="OK",
    )
    deck = EmittedOpmDeck(
        data_file=data_file,
        schedule_file=schedule_file,
        summary_file=summary_file,
        summary_plan=None,  # type: ignore[arg-type]
        input_files=(data_file, schedule_file, summary_file),
        content_hash_opm="content",
    )
    return generator, result, deck, schedule_file, dataset_root


def test_compaction_keeps_the_materialized_schedule_on_disk(tmp_path: Path) -> None:
    generator, result, deck, schedule_file, dataset_root = _compaction_fixture(tmp_path)
    payload = schedule_file.read_bytes()

    generator._compact_verified_response(
        result, deck, response_hash="a" * 64, scenario_id="scenario-1"
    )

    assert not deck.data_file.parent.exists()
    retained = dataset_root / SCHEDULES_DIR / "scenario-1.inc"
    assert retained.is_file()
    assert retained.read_bytes() == payload


def test_retention_policy_is_declared_and_disjoint() -> None:
    assert ALWAYS_RETAINED
    assert COMPACTED_ON_REQUEST
    assert not set(ALWAYS_RETAINED) & set(COMPACTED_ON_REQUEST)
    assert any("расписание" in item for item in ALWAYS_RETAINED)


def test_compaction_reports_a_missing_schedule_instead_of_silently_dropping_it(
    tmp_path: Path,
) -> None:
    generator, result, deck, schedule_file, _ = _compaction_fixture(tmp_path)
    schedule_file.unlink()

    with pytest.raises(DatasetError) as error:
        generator._compact_verified_response(
            result, deck, response_hash="a" * 64, scenario_id="scenario-1"
        )
    assert "расписание" in str(error.value)
    assert deck.data_file.parent.exists()
