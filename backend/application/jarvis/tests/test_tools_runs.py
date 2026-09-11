from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore, RunStore
from backend.contexts.assistant.infrastructure.knowledge import Knowledge
from backend.contexts.assistant.application.orchestrator import Orchestrator
from backend.contexts.assistant.application.tools import run_tool, tool_specs
from backend.contexts.assistant.application.tools.context import (
    ConsoleContext,
    ToolContext,
    ToolFailure,
)
from backend.contexts.assistant.application.tools.runs import NO_SUBMISSION
from backend.contexts.runs.application.workflow import (
    RunProvenance,
    RunRequest,
    RunWorkflow,
    SUBMISSION_BUNDLE_FIELDS,
)
from backend.core.contracts import (
    Availability,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    SubmissionBundle,
    WellState,
)
from backend.contexts.assistant.infrastructure.llm.chat_events import ToolCall
from backend.contexts.assistant.infrastructure.llm.fake_chat import FakeChatClient

RUN_ID = "jarvis-run"
PREDICTED_NPV = 12_345_678.5
VERIFIED_NPV = 11_873_122_324.91
CLAIMED_NPV = 11_873_122_324.91
SEARCH_STRATEGY = "cmaes-restart"


@dataclass(frozen=True)
class FakeVerification:
    sound: bool
    npv_methodology: float | None


def sample_schedule() -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("W1",)),
        initial_state={
            "W1": WellState(
                Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, 10.0
            )
        },
        fixed_deck_events=(),
        control_events=(),
    )


def make_run(
    runs_root: Path,
    run_id: str = RUN_ID,
    *,
    sound: bool = True,
    search_strategy: str | None = SEARCH_STRATEGY,
) -> Path:
    workflow = RunWorkflow(runs_root)
    workflow.verify(
        RunRequest(
            run_id,
            sample_schedule(),
            predicted_npv=PREDICTED_NPV,
            provenance=RunProvenance(
                deck_hash="c" * 64,
                constraints_hash="b" * 64,
                opm_image="openporousmedia/opmreleases:latest",
                git_commit="e" * 40,
                search_strategy=search_strategy,
                seed="7",
                iterations=240,
                self_consistent=True,
            ),
        ),
        lambda _schedule, _opm: FakeVerification(
            sound, VERIFIED_NPV if sound else None
        ),
    )
    return runs_root / run_id


def write_submission(run_dir: Path, claimed: float = CLAIMED_NPV) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    bundle = SubmissionBundle(
        canonical_schedule_hash=str(manifest["schedule_hash"]),
        content_hash_submission="d" * 64,
        claimed_npv_rub=claimed,
        source_run_id=str(manifest["run_id"]),
        response_hash="f" * 64,
        deck_hash=str(manifest["deck_hash"]),
        economics_config_hash="a" * 64,
        methodology_version_hash="9" * 64,
        constraints_hash=str(manifest["constraints_hash"]),
        opm_image=str(manifest["opm_image"]),
        git_commit=str(manifest["git_commit"]),
        created_at="2026-09-09T10:00:00+00:00",
    )
    document = {name: getattr(bundle, name) for name in SUBMISSION_BUNDLE_FIELDS}
    submission_dir = run_dir / "submission"
    submission_dir.mkdir(parents=True, exist_ok=True)
    (submission_dir / "claimed_npv.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (submission_dir / "well_schedule.inc").write_bytes(b"SCHEDULE\n/\n")
    manifest["status"] = "ready_to_submit"
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document


def make(store: ArtifactStore, runs_root: Path, **console: object) -> ToolContext:
    return ToolContext(
        store=store,
        console=ConsoleContext(**console),
        runs=RunStore(runs_root),
    )


@pytest.fixture()
def runs_root(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def test_both_run_tools_are_registered() -> None:
    names = {spec.name for spec in tool_specs()}
    assert "run_status" in names
    assert "submission_summary" in names


def test_run_status_reports_the_numbers_of_the_manifest(
    store: ArtifactStore, runs_root: Path
) -> None:
    run_dir = make_run(runs_root)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    card = run_tool("run_status", make(store, runs_root), {"run_id": RUN_ID})

    assert card.type == "run-status"
    assert card.payload["run_id"] == RUN_ID
    assert card.payload["status"] == manifest["status"] == "verified"
    assert card.payload["predicted_npv"] == manifest["predicted_npv"] == PREDICTED_NPV
    assert card.payload["verified_npv"] == manifest["verified_npv"] == VERIFIED_NPV
    assert card.payload["sound"] is True
    assert card.payload["search_strategy"] == SEARCH_STRATEGY
    assert card.payload["schedule_hash"] == manifest["schedule_hash"]
    assert card.provenance == "run-manifest"


def test_run_status_reports_the_recorded_violations(
    store: ArtifactStore, runs_root: Path
) -> None:
    run_dir = make_run(runs_root)
    recorded = json.loads(
        (run_dir / "validation" / "result.json").read_text(encoding="utf-8")
    )

    card = run_tool("run_status", make(store, runs_root), {"run_id": RUN_ID})

    violations = card.payload["violations"]
    assert violations["recorded"] is True
    assert violations["dynamic"] == recorded["dynamic_violations"]
    assert violations["blocking"] == recorded["blocking_dynamic_violations"]


def test_run_status_reads_the_latest_run_without_an_identifier(
    store: ArtifactStore, runs_root: Path
) -> None:
    older = make_run(runs_root, "older")
    newer = make_run(runs_root, "newer")
    stamp = time.time()
    os.utime(older / "manifest.json", (stamp - 100.0, stamp - 100.0))
    os.utime(newer / "manifest.json", (stamp, stamp))

    card = run_tool("run_status", make(store, runs_root), {})

    assert card.payload["run_id"] == "newer"
    assert card.payload["status"] == "verified"


def test_run_status_refuses_a_run_that_does_not_exist(
    store: ArtifactStore, runs_root: Path
) -> None:
    make_run(runs_root)

    with pytest.raises(ToolFailure) as error:
        run_tool("run_status", make(store, runs_root), {"run_id": "no-such-run"})

    message = str(error.value)
    assert "no-such-run" in message
    assert "не найден" in message
    assert RUN_ID in message


def test_run_status_refuses_when_no_run_was_ever_made(
    store: ArtifactStore, runs_root: Path
) -> None:
    runs_root.mkdir(parents=True)

    with pytest.raises(ToolFailure) as error:
        run_tool("run_status", make(store, runs_root), {})

    assert "ни одного прогона" in str(error.value)


def test_unrecorded_manifest_field_is_reported_as_not_recorded(
    store: ArtifactStore, runs_root: Path
) -> None:
    make_run(runs_root, search_strategy=None)

    card = run_tool("run_status", make(store, runs_root), {"run_id": RUN_ID})

    assert card.payload["search_strategy"] is None
    assert "search_strategy" in card.payload["not_recorded"]
    assert "model_version" in card.payload["not_recorded"]
    assert card.payload["not_recorded_marker"] == "not-recorded"


def test_recorded_field_is_not_listed_as_missing(
    store: ArtifactStore, runs_root: Path
) -> None:
    make_run(runs_root)

    card = run_tool("run_status", make(store, runs_root), {"run_id": RUN_ID})

    assert "search_strategy" not in card.payload["not_recorded"]
    assert "deck_hash" not in card.payload["not_recorded"]
    assert card.payload["provenance_fields"]["iterations"] == 240
    assert card.payload["provenance_fields"]["self_consistent"] is True


def test_unsound_run_reports_no_verified_npv_instead_of_zero(
    store: ArtifactStore, runs_root: Path
) -> None:
    make_run(runs_root, "rejected-run", sound=False)

    card = run_tool("run_status", make(store, runs_root), {"run_id": "rejected-run"})

    assert card.payload["status"] == "rejected"
    assert card.payload["sound"] is False
    assert card.payload["verified_npv"] is None
    assert "verified_npv" in card.payload["not_recorded"]


def test_submission_summary_says_plainly_that_no_package_exists(
    store: ArtifactStore, runs_root: Path
) -> None:
    make_run(runs_root)

    card = run_tool("submission_summary", make(store, runs_root), {"run_id": RUN_ID})

    assert card.type == "submission"
    assert card.payload["assembled"] is False
    assert card.payload["code"] == NO_SUBMISSION
    assert card.payload["claimed_npv_rub"] is None
    assert card.payload["hashes"] is None
    assert "не собран" in card.payload["reason"]


def test_submission_summary_reports_the_numbers_of_the_package(
    store: ArtifactStore, runs_root: Path
) -> None:
    run_dir = make_run(runs_root)
    document = write_submission(run_dir)

    card = run_tool("submission_summary", make(store, runs_root), {"run_id": RUN_ID})

    assert card.payload["assembled"] is True
    assert card.payload["claimed_npv_rub"] == document["claimed_npv_rub"] == CLAIMED_NPV
    for name in SUBMISSION_BUNDLE_FIELDS:
        if name == "claimed_npv_rub":
            continue
        assert card.payload["hashes"][name] == document[name]
    assert card.payload["status"] == "ready_to_submit"


def test_submission_summary_checks_the_package_against_the_manifest(
    store: ArtifactStore, runs_root: Path
) -> None:
    run_dir = make_run(runs_root)
    write_submission(run_dir)

    card = run_tool("submission_summary", make(store, runs_root), {"run_id": RUN_ID})

    checks = card.payload["checks"]
    assert checks["status_ready_to_submit"] is True
    assert checks["schedule_include_present"] is True
    assert checks["source_run_matches"] is True
    assert checks["schedule_hash_matches"] is True
    assert checks["missing_fields"] == []


def test_submission_summary_refuses_a_package_without_a_number(
    store: ArtifactStore, runs_root: Path
) -> None:
    run_dir = make_run(runs_root)
    write_submission(run_dir)
    path = run_dir / "submission" / "claimed_npv.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["claimed_npv_rub"] = None
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ToolFailure) as error:
        run_tool("submission_summary", make(store, runs_root), {"run_id": RUN_ID})

    assert "claimed_npv_rub" in str(error.value)


def test_the_scene_carries_the_claimed_number_through_the_guard(
    store: ArtifactStore, runs_root: Path
) -> None:
    run_dir = make_run(runs_root)
    write_submission(run_dir)
    call = ToolCall(id="c", name="submission_summary", args={"run_id": RUN_ID})
    client = FakeChatClient(
        rounds=[[call]], caption="Заявленный ЧДД пакета — 11 873 676 460 руб."
    )
    orchestrator = Orchestrator(
        client=client,
        store=store,
        knowledge=Knowledge(),
        runs=RunStore(runs_root),
    )

    events = list(orchestrator.ask("s", "что с пакетом сдачи", ConsoleContext()))

    caption = [event for event in events if event.type == "caption"][0]
    assert "11 873 676 460" in caption.body["text"]
    assert not [event for event in events if event.type == "warning"]


def test_the_guard_still_cuts_an_invented_number_in_a_run_scene(
    store: ArtifactStore, runs_root: Path
) -> None:
    run_dir = make_run(runs_root)
    write_submission(run_dir)
    call = ToolCall(id="c", name="submission_summary", args={"run_id": RUN_ID})
    client = FakeChatClient(rounds=[[call]], caption="Запас составил 777 555 руб.")
    orchestrator = Orchestrator(
        client=client,
        store=store,
        knowledge=Knowledge(),
        runs=RunStore(runs_root),
    )

    events = list(orchestrator.ask("s", "что с пакетом сдачи", ConsoleContext()))

    caption = [event for event in events if event.type == "caption"][0]
    assert "777 555" not in caption.body["text"]


def test_the_manifest_number_passes_the_guard_without_a_run_card(
    store: ArtifactStore, runs_root: Path
) -> None:
    make_run(runs_root)
    call = ToolCall(id="c", name="field_metrics", args={"step": 96})
    client = FakeChatClient(rounds=[[call]], caption="Прогноз прогона — 12 345 679 руб.")
    orchestrator = Orchestrator(
        client=client,
        store=store,
        knowledge=Knowledge(),
        runs=RunStore(runs_root),
    )

    events = list(orchestrator.ask("s", "что с последним расчётом", ConsoleContext()))

    caption = [event for event in events if event.type == "caption"][0]
    assert "12 345 679" in caption.body["text"]
