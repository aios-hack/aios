import json
from dataclasses import dataclass

import pytest

from backend.application.runs import (
    MANIFEST_FIELDS,
    MANIFEST_PROVENANCE_FIELDS,
    RunManifest,
    RunProvenance,
    RunRequest,
    RunWorkflow,
    WorkflowStatus,
)
from backend.core.contracts import (
    Availability,
    Constraints,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellOutage,
    WellState,
)
from backend.domain.configuration.constraints_io import (
    constraints_from_json,
    constraints_hash,
    constraints_to_json,
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
    assert json.loads((run_dir / "inputs" / "request.json").read_text())["run_id"] == "good-plan"


def test_unsound_opm_result_is_rejected(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")

    result = workflow.verify(
        RunRequest("bad-plan", sample_schedule()),
        lambda _schedule, _opm: FakeVerification(False, 10.0),
    )

    assert result.status is WorkflowStatus.REJECTED
    assert result.sound is False


def test_full_passes_the_schedule_returned_by_search_to_verification(tmp_path) -> None:
    schedule = sample_schedule()
    workflow = RunWorkflow(tmp_path / "runs")
    seen = []

    result = workflow.full(
        lambda: RunRequest("full-plan", schedule, predicted_npv=12.5),
        lambda actual, _opm: (seen.append(actual) or FakeVerification(True, 11.0)),
    )

    assert seen == [schedule]
    assert result.status is WorkflowStatus.READY_TO_SUBMIT


def test_unsound_real_style_result_preserves_diagnostics_without_reading_npv(tmp_path):
    class Rejected:
        sound = False
        @property
        def npv_methodology(self):
            raise ValueError('unverified NPV must not be read')
    result = RunWorkflow(tmp_path).verify(RunRequest('rejected', sample_schedule()), lambda *_: Rejected())
    assert result.verified_npv is None
    assert result.sound is False
    assert (tmp_path / 'rejected/validation/result.json').is_file()


def sample_constraints() -> Constraints:
    return Constraints(
        liquid_limits={2010: 38000.0},
        watercut_limits={2012: 0.95},
        well_outages=(WellOutage("P12", 48, 51),),
        infrastructure={"external_water_m3_per_day": 5000.0},
    )


def full_provenance() -> RunProvenance:
    return RunProvenance(
        model_version="surrogate-1.4.0",
        npv_head_version="npv-head-2.1",
        scenario_ood_version="ood-3",
        feature_context_sha256="a" * 64,
        constraints_hash="b" * 64,
        deck_hash="c" * 64,
        normatives_sha256="d" * 64,
        opm_image="openporousmedia/opmreleases:latest",
        git_commit="e" * 40,
        seed="20260816",
        search_strategy="cma-es",
        policy_equilibrium="reached",
        iterations=120,
        self_consistent=True,
    )


def test_manifest_dict_carries_every_declared_field() -> None:
    manifest = RunManifest("r1", WorkflowStatus.SEARCHED, "hash", 1.0, None, None)

    assert tuple(manifest.as_dict()) == MANIFEST_FIELDS


def test_manifest_dict_names_all_provenance_fields() -> None:
    document = RunManifest("r1", WorkflowStatus.SEARCHED, "hash", None, None, None).as_dict()

    for name in MANIFEST_PROVENANCE_FIELDS:
        assert name in document, name
        assert document[name] is None


def test_provenance_reaches_the_manifest_of_a_searched_run(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    request = RunRequest("traced", sample_schedule(), 12.5, provenance=full_provenance())

    manifest = workflow.search(request)

    document = json.loads(
        (tmp_path / "runs" / "traced" / "manifest.json").read_text(encoding="utf-8")
    )
    assert document["model_version"] == "surrogate-1.4.0"
    assert document["normatives_sha256"] == "d" * 64
    assert document["constraints_hash"] == "b" * 64
    assert document["deck_hash"] == "c" * 64
    assert document["opm_image"] == "openporousmedia/opmreleases:latest"
    assert document["git_commit"] == "e" * 40
    assert document["seed"] == "20260816"
    assert document["search_strategy"] == "cma-es"
    assert document["policy_equilibrium"] == "reached"
    assert document["iterations"] == 120
    assert document["self_consistent"] is True
    assert manifest.feature_context_sha256 == "a" * 64
    assert manifest.scenario_ood_version == "ood-3"
    assert manifest.npv_head_version == "npv-head-2.1"


def test_a_manifest_written_before_provenance_existed_still_reads() -> None:
    legacy = {
        "run_id": "old-run",
        "status": "ready_to_submit",
        "schedule_hash": "f" * 64,
        "predicted_npv": 12.0,
        "verified_npv": 11.0,
        "sound": True,
    }

    manifest = RunManifest.from_dict(legacy)

    assert manifest.run_id == "old-run"
    assert manifest.status is WorkflowStatus.READY_TO_SUBMIT
    assert manifest.verified_npv == 11.0
    for name in MANIFEST_PROVENANCE_FIELDS:
        assert getattr(manifest, name) is None


def test_a_manifest_file_written_before_provenance_existed_still_reads(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "old-run",
                "status": "rejected",
                "schedule_hash": "0" * 64,
                "predicted_npv": None,
                "verified_npv": None,
                "sound": False,
            }
        ),
        encoding="utf-8",
    )

    manifest = RunManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    assert manifest.status is WorkflowStatus.REJECTED
    assert manifest.as_dict()["deck_hash"] is None


def test_a_manifest_missing_its_identity_is_refused_not_guessed() -> None:
    with pytest.raises(ValueError, match="schedule_hash"):
        RunManifest.from_dict({"run_id": "r", "status": "searched"})


def test_a_run_without_provenance_keeps_every_new_field_empty(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")

    manifest = workflow.search(RunRequest("plain", sample_schedule()))

    for name in MANIFEST_PROVENANCE_FIELDS:
        assert getattr(manifest, name) is None


def test_the_case_is_copied_into_the_run_directory(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    constraints = sample_constraints()

    workflow.search(RunRequest("with-case", sample_schedule(), constraints=constraints))

    copied = tmp_path / "runs" / "with-case" / "inputs" / "constraints.json"
    assert copied.is_file()
    assert json.loads(copied.read_text(encoding="utf-8")) == constraints_to_json(constraints)


def test_the_copied_case_reloads_into_the_same_constraints(tmp_path) -> None:
    constraints = sample_constraints()
    RunWorkflow(tmp_path / "runs").search(
        RunRequest("reloadable", sample_schedule(), constraints=constraints)
    )

    copied = tmp_path / "runs" / "reloadable" / "inputs" / "constraints.json"
    restored = constraints_from_json(json.loads(copied.read_text(encoding="utf-8")))

    assert constraints_hash(restored) == constraints_hash(constraints)


def test_verification_also_copies_the_case_it_was_given(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")

    workflow.verify(
        RunRequest("verified-case", sample_schedule(), constraints=sample_constraints()),
        lambda _schedule, _opm: FakeVerification(True, 11.0),
    )

    assert (tmp_path / "runs" / "verified-case" / "inputs" / "constraints.json").is_file()


def test_no_case_file_is_written_when_no_case_was_supplied(tmp_path) -> None:
    RunWorkflow(tmp_path / "runs").search(RunRequest("no-case", sample_schedule()))

    assert not (tmp_path / "runs" / "no-case" / "inputs" / "constraints.json").exists()


def test_the_deck_hash_of_the_real_opm_run_overrides_the_declared_one(tmp_path) -> None:
    @dataclass(frozen=True)
    class OpmRun:
        deck_hash: str

    @dataclass(frozen=True)
    class Verified:
        sound: bool
        npv_methodology: float | None
        opm_run: OpmRun

    manifest = RunWorkflow(tmp_path / "runs").verify(
        RunRequest("measured", sample_schedule(), provenance=full_provenance()),
        lambda _schedule, _opm: Verified(True, 11.0, OpmRun("9" * 64)),
    )

    assert manifest.deck_hash == "9" * 64


def test_a_verification_without_an_opm_run_keeps_the_declared_deck_hash(tmp_path) -> None:
    manifest = RunWorkflow(tmp_path / "runs").verify(
        RunRequest("declared", sample_schedule(), provenance=full_provenance()),
        lambda _schedule, _opm: FakeVerification(True, 11.0),
    )

    assert manifest.deck_hash == "c" * 64
