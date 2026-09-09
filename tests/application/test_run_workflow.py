import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

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
from backend.application.runs.workflow import SubmissionError
from backend.core.contracts import (
    ActiveControlMode,
    Availability,
    Constraints,
    IntervalResponse,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    StateAtDate,
    SubmissionBundle,
    T0,
    WellOutage,
    WellState,
    content_hash,
    hash_schedule,
)
from backend.domain.configuration.constraints_io import (
    constraints_from_json,
    constraints_hash,
    constraints_to_json,
)
from backend.domain.schedule import parse_schedule
from backend.domain.schedule.build import build_schedule
from backend.domain.schedule.emit import ScheduleEmitError, verify_schedule_round_trip
from backend.domain.schedule.validate_dynamic import (
    FIRST_CONTROL_DECK_DATE_INDEX,
    DynamicReport,
    validate_dynamic,
)
from backend.infrastructure.opm.opm_deck import (
    render_control_period_include,
    render_schedule_include,
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


def test_verified_run_has_complete_layout_and_verified_status(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    request = RunRequest("good-plan", sample_schedule(), predicted_npv=12.5)

    result = workflow.verify(request, lambda _schedule, _opm: FakeVerification(True, 11.0))

    assert result.status is WorkflowStatus.VERIFIED
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
    assert result.status is WorkflowStatus.VERIFIED


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


MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)
SYNTHETIC_STEPS = 4


def synthetic_schedule_include() -> bytes:
    parts = [
        b"RPTSCHED\n 'WELLS=1' 'SUMMARY=1' 'RESTART=0' /\n\n"
        b"WELSPECS\n 'W1' 'GROUP' 23 17 1* 'OIL' /\n"
        b" 'W2' 'GROUP' 47 40 1* 'OIL' /\n/\n\n"
    ]
    for step in range(SYNTHETIC_STEPS + 1):
        month = MONTHS[step % 12]
        year = 2007 + step // 12
        parts.append(f"DATES\n 01 {month} {year} /\n/\n\n".encode())
        if step < SYNTHETIC_STEPS:
            parts.append(
                f"WCONPROD\n 'W1' 'OPEN' 'LRAT' 1* 1* 1* {100.0 + step} 1* 50 1* 1* /\n/\n\n"
                f"WCONINJE\n 'W2' 'WATER' 'OPEN' 'RATE' {200.0 + step} 1* 300 1* 1* /\n/\n\n".encode()
            )
    return b"".join(parts)


def synthetic_model_dir(root: Path) -> Path:
    model_dir = root / "Model_Z"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "Model_Z_sch.inc").write_bytes(synthetic_schedule_include())
    (model_dir / "Model_Z.data").write_bytes(
        b"RUNSPEC\nDIMENS\n 10 10 3 /\nSCHEDULE\nINCLUDE\n 'Model_Z_sch.inc' /\n"
    )
    return model_dir


def emittable_schedule() -> Schedule:
    raw = synthetic_schedule_include()
    return build_schedule(
        parse_schedule(raw), raw, model="Model_Z", provenance="synthetic"
    )


@dataclass(frozen=True)
class FakeFinalNpv:
    npv_methodology: float
    source_run_id: str = "opm-run-1"
    source_response_hash: str = "1" * 64
    economics_config_hash: str = "2" * 64
    methodology_version_hash: str = "3" * 64


@dataclass(frozen=True)
class FakeOpmRun:
    deck_hash: str = "4" * 64


@dataclass(frozen=True)
class FakeSubmittableVerification:
    sound: bool
    npv_methodology: float | None
    final_npv: FakeFinalNpv | None
    opm_run: FakeOpmRun = FakeOpmRun()


def submittable_provenance() -> RunProvenance:
    return RunProvenance(
        constraints_hash="b" * 64,
        deck_hash="c" * 64,
        opm_image="openporousmedia/opmreleases:latest",
        git_commit="e" * 40,
    )


CLAIMED_NPV = 11_873_676_459.64


def prepare_submittable_run(
    tmp_path: Path, run_id: str = "submittable", *, sound: bool = True
) -> tuple[RunWorkflow, Path]:
    workflow = RunWorkflow(tmp_path / "runs")
    workflow.verify(
        RunRequest(
            run_id,
            emittable_schedule(),
            predicted_npv=12.0,
            provenance=submittable_provenance(),
        ),
        lambda _schedule, _opm: FakeSubmittableVerification(
            sound, CLAIMED_NPV if sound else None, FakeFinalNpv(CLAIMED_NPV)
        ),
    )
    return workflow, synthetic_model_dir(tmp_path / "model")


def test_verify_stops_at_verified_and_does_not_promise_submission(tmp_path) -> None:
    prepare_submittable_run(tmp_path)

    manifest = RunManifest.from_dict(
        json.loads(
            (tmp_path / "runs" / "submittable" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
    )

    assert manifest.status is WorkflowStatus.VERIFIED
    assert not (tmp_path / "runs" / "submittable" / "submission").exists()


def test_submit_builds_the_package_of_a_sound_run(tmp_path) -> None:
    workflow, model_dir = prepare_submittable_run(tmp_path)

    report = workflow.submit("submittable", model_dir)

    assert report.schedule_path.is_file()
    assert report.schedule_path.name == "wells_schedule.inc"
    assert report.manifest.status is WorkflowStatus.READY_TO_SUBMIT
    document = json.loads(
        (report.directory / "claimed_npv.json").read_text(encoding="utf-8")
    )
    restored = SubmissionBundle(**document)
    assert restored == report.bundle
    assert restored.claimed_npv_rub == CLAIMED_NPV
    assert restored.canonical_schedule_hash == hash_schedule(emittable_schedule())


def test_the_package_bytes_are_the_ones_that_were_hashed(tmp_path) -> None:
    workflow, model_dir = prepare_submittable_run(tmp_path)

    report = workflow.submit("submittable", model_dir)

    raw = report.schedule_path.read_bytes()
    assert content_hash(raw) == report.bundle.content_hash_submission
    verify_schedule_round_trip(emittable_schedule(), raw).raise_if_broken()


def test_submit_copies_the_evidence_next_to_the_claimed_number(tmp_path) -> None:
    workflow, model_dir = prepare_submittable_run(tmp_path)
    (tmp_path / "runs" / "submittable" / "provenance.json").write_text(
        json.dumps({"seed": "20260816"}), encoding="utf-8"
    )

    report = workflow.submit("submittable", model_dir)

    assert (report.directory / "validation" / "result.json").is_file()
    copied = report.directory / "provenance.json"
    assert json.loads(copied.read_text(encoding="utf-8")) == {"seed": "20260816"}


def test_an_unsound_run_gets_no_package(tmp_path) -> None:
    workflow, model_dir = prepare_submittable_run(tmp_path, "unsound", sound=False)

    with pytest.raises(SubmissionError, match="sound"):
        workflow.submit("unsound", model_dir)

    assert not (tmp_path / "runs" / "unsound" / "submission").exists()


def test_a_run_without_an_opm_npv_gets_no_package_and_no_forecast(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    workflow.verify(
        RunRequest(
            "npv-less",
            emittable_schedule(),
            predicted_npv=99.0,
            provenance=submittable_provenance(),
        ),
        lambda _schedule, _opm: FakeSubmittableVerification(True, None, None),
    )
    model_dir = synthetic_model_dir(tmp_path / "model")

    with pytest.raises(SubmissionError, match="npv_methodology"):
        workflow.submit("npv-less", model_dir)

    assert not (tmp_path / "runs" / "npv-less" / "submission").exists()


def test_a_run_without_a_deck_hash_is_refused_instead_of_invented(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    workflow.verify(
        RunRequest(
            "hashless",
            emittable_schedule(),
            provenance=RunProvenance(constraints_hash="b" * 64, git_commit="e" * 40),
        ),
        lambda _schedule, _opm: FakeSubmittableVerification(
            True, CLAIMED_NPV, FakeFinalNpv(CLAIMED_NPV), None
        ),
    )
    model_dir = synthetic_model_dir(tmp_path / "model")

    with pytest.raises(SubmissionError, match="deck_hash"):
        workflow.submit("hashless", model_dir)

    assert not (tmp_path / "runs" / "hashless" / "submission").exists()


def test_submit_is_idempotent(tmp_path) -> None:
    workflow, model_dir = prepare_submittable_run(tmp_path)

    first = workflow.submit("submittable", model_dir)
    first_names = sorted(path.name for path in first.directory.iterdir())
    second = workflow.submit("submittable", model_dir)

    assert second.bundle == first.bundle
    assert sorted(path.name for path in second.directory.iterdir()) == first_names
    assert second.schedule_path.read_bytes() == first.schedule_path.read_bytes()


def test_a_broken_round_trip_gives_no_package(tmp_path, monkeypatch) -> None:
    workflow, model_dir = prepare_submittable_run(tmp_path, "tampered")
    genuine = render_control_period_include(emittable_schedule(), model_dir)
    tampered = genuine.raw.replace(b"'W1' 'OPEN' 'LRAT'", b"'W1' 'SHUT' 'LRAT'", 1)
    assert tampered != genuine.raw
    monkeypatch.setattr(
        "backend.application.runs.workflow.render_control_period_include",
        lambda schedule, directory: replace(genuine, raw=tampered),
    )

    with pytest.raises(ScheduleEmitError):
        workflow.submit("tampered", model_dir)

    assert not (tmp_path / "runs" / "tampered" / "submission").exists()


def test_submit_refuses_a_run_that_does_not_exist(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")

    with pytest.raises(SubmissionError, match="absent"):
        workflow.submit("absent", synthetic_model_dir(tmp_path / "model"))


SYNTHETIC_HISTORY_STEPS = 5


def synthetic_schedule_include_with_history() -> bytes:
    parts = [
        b"RPTSCHED\n 'WELLS=1' 'SUMMARY=1' 'RESTART=0' /\n\n"
        b"WELSPECS\n 'W1' 'GROUP' 23 17 1* 'OIL' /\n"
        b" 'W2' 'GROUP' 47 40 1* 'OIL' /\n/\n\n"
    ]
    for step in range(SYNTHETIC_HISTORY_STEPS):
        month = MONTHS[(step + 7) % 12]
        parts.append(f"DATES\n 01 {month} 2006 /\n/\n\n".encode())
        parts.append(
            f"WCONPROD\n 'W1' 'OPEN' 'LRAT' 1* 1* 1* {10.0 + step} 1* 50 1* 1* /\n/\n\n"
            f"WCONINJE\n 'W2' 'WATER' 'OPEN' 'RATE' {20.0 + step} 1* 300 1* 1* /\n/\n\n".encode()
        )
    for step in range(SYNTHETIC_STEPS + 1):
        month = MONTHS[step % 12]
        year = 2007 + step // 12
        parts.append(f"DATES\n 01 {month} {year} /\n/\n\n".encode())
        if step < SYNTHETIC_STEPS:
            parts.append(
                f"WCONPROD\n 'W1' 'OPEN' 'LRAT' 1* 1* 1* {100.0 + step} 1* 50 1* 1* /\n/\n\n"
                f"WCONINJE\n 'W2' 'WATER' 'OPEN' 'RATE' {200.0 + step} 1* 300 1* 1* /\n/\n\n".encode()
            )
    return b"".join(parts)


def historical_model_dir(root: Path) -> Path:
    model_dir = root / "Model_Z"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "Model_Z_sch.inc").write_bytes(synthetic_schedule_include_with_history())
    (model_dir / "Model_Z.data").write_bytes(
        b"RUNSPEC\nDIMENS\n 10 10 3 /\nSCHEDULE\nINCLUDE\n 'Model_Z_sch.inc' /\n"
    )
    return model_dir


def historical_schedule() -> Schedule:
    raw = synthetic_schedule_include_with_history()
    return build_schedule(
        parse_schedule(raw), raw, model="Model_Z", provenance="synthetic"
    )


def prepare_historical_run(tmp_path: Path) -> tuple[RunWorkflow, Path]:
    workflow = RunWorkflow(tmp_path / "runs")
    workflow.verify(
        RunRequest(
            "historical",
            historical_schedule(),
            predicted_npv=12.0,
            provenance=submittable_provenance(),
        ),
        lambda _schedule, _opm: FakeSubmittableVerification(
            True, CLAIMED_NPV, FakeFinalNpv(CLAIMED_NPV)
        ),
    )
    return workflow, historical_model_dir(tmp_path / "model")


def test_submitted_file_carries_no_event_from_the_historical_part(tmp_path) -> None:
    workflow, model_dir = prepare_historical_run(tmp_path)

    report = workflow.submit("historical", model_dir)
    parsed = parse_schedule(report.schedule_path.read_bytes())

    before_t0 = [
        block
        for block in parsed.blocks
        if block.event_date is not None and block.event_date < T0
    ]
    assert [block.keyword for block in before_t0] == [
        "DATES",
        "WCONPROD",
        "WCONINJE",
    ]
    assert before_t0[0].event_date == date(2006, 12, 1)
    assert all(block.control_step is None for block in before_t0)
    assert all(
        event.control_step >= 0
        for event in parsed.control_events + parsed.fixed_deck_events
    )


def test_submitted_file_drops_the_historical_dates_the_deck_carries(tmp_path) -> None:
    workflow, model_dir = prepare_historical_run(tmp_path)
    source = parse_schedule((model_dir / "Model_Z_sch.inc").read_bytes())

    report = workflow.submit("historical", model_dir)
    submitted = parse_schedule(report.schedule_path.read_bytes())

    assert len(source.dates) == SYNTHETIC_HISTORY_STEPS + SYNTHETIC_STEPS + 1
    assert len(submitted.dates) == SYNTHETIC_STEPS + 2
    assert submitted.dates[1:] == source.dates[SYNTHETIC_HISTORY_STEPS:]


def test_the_number_of_control_blocks_matches_the_managed_period(tmp_path) -> None:
    workflow, model_dir = prepare_historical_run(tmp_path)

    report = workflow.submit("historical", model_dir)
    parsed = parse_schedule(report.schedule_path.read_bytes())

    managed = [
        block
        for block in parsed.blocks
        if block.keyword in ("WCONPROD", "WCONINJE")
        and block.control_step is not None
        and block.control_events
    ]
    assert len(managed) == 2 * SYNTHETIC_STEPS
    assert {block.control_step for block in managed} == set(range(SYNTHETIC_STEPS))
    assert max(event.control_step for event in parsed.control_events) == (
        SYNTHETIC_STEPS - 1
    )


def test_the_submitted_control_period_still_round_trips(tmp_path) -> None:
    workflow, model_dir = prepare_historical_run(tmp_path)
    schedule = historical_schedule()

    report = workflow.submit("historical", model_dir)
    raw = report.schedule_path.read_bytes()

    verify_schedule_round_trip(schedule, raw).raise_if_broken()
    assert content_hash(raw) == report.bundle.content_hash_submission
    assert report.bundle.canonical_schedule_hash == hash_schedule(schedule)


def test_the_control_period_file_is_smaller_than_the_full_deck(tmp_path) -> None:
    workflow, model_dir = prepare_historical_run(tmp_path)
    schedule = historical_schedule()

    report = workflow.submit("historical", model_dir)
    full = render_schedule_include(schedule, model_dir)

    submitted = report.schedule_path.read_bytes()
    assert len(submitted) < len(full.raw)
    for month in (b"01 AUG 2006", b"01 SEP 2006", b"01 OCT 2006", b"01 NOV 2006"):
        assert month in full.raw
        assert month not in submitted


def constrained_report(constraints: Constraints | None) -> DynamicReport:
    schedule = Schedule(
        meta=ScheduleMeta(wells=("W1",), n_intervals=2),
        initial_state={
            "W1": WellState(
                Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, 10.0
            )
        },
        fixed_deck_events=(),
        control_events=(),
    )
    n_dates = schedule.meta.n_intervals + FIRST_CONTROL_DECK_DATE_INDEX + 1
    states = tuple(
        StateAtDate(
            deck_date_index=index,
            well="W1",
            liquid_rate=0.0,
            oil_rate=0.0,
            injection_rate=0.0,
            thp=20.0,
            bhp=120.0,
            well_efficiency=1.0,
            active_control_mode=ActiveControlMode.RATE_TARGET,
        )
        for index in range(n_dates)
    )
    intervals = tuple(
        IntervalResponse(
            control_step=step,
            well="W1",
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=0.0,
        )
        for step in range(schedule.meta.n_intervals)
    )
    return validate_dynamic(
        schedule, states, intervals, constraints, oil_density_t_per_m3=0.85
    )


@dataclass(frozen=True)
class ReportedVerification:
    sound: bool
    npv_methodology: float | None
    dynamic_report: DynamicReport | None


def constraints_report_of(run_dir: Path) -> dict[str, object]:
    path = run_dir / "validation" / "constraints_report.json"
    assert path.is_file(), f"отчёт о применённых ограничениях не записан: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_verify_writes_the_constraints_report_next_to_the_validation_result(
    tmp_path,
) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    constraints = sample_constraints()
    request = RunRequest("reported", sample_schedule(), constraints=constraints)

    workflow.verify(
        request,
        lambda _s, _o: ReportedVerification(
            True, 11.0, constrained_report(constraints)
        ),
    )

    document = constraints_report_of(tmp_path / "runs" / "reported")
    assert document["constraints_hash"] == constraints_hash(constraints)
    assert document["unavailable_reason"] is None
    names = {item["constraint"] for item in document["checks"]}
    assert names == {
        item.constraint for item in constrained_report(constraints).constraint_checks
    }


def test_constraints_report_separates_checked_and_unset(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    constraints = Constraints(
        liquid_limits={2007: 1.0},
        infrastructure={
            "compensation_min": 0.5,
            "compensation_max": 1.5,
            "compensation_scope": "field",
        },
    )
    workflow.verify(
        RunRequest("statuses", sample_schedule(), constraints=constraints),
        lambda _s, _o: ReportedVerification(
            True, 1.0, constrained_report(constraints)
        ),
    )

    document = constraints_report_of(tmp_path / "runs" / "statuses")
    statuses = {item["constraint"]: item["status"] for item in document["checks"]}
    assert statuses["liquid_limits"] == "checked"
    assert statuses["injection_limits"] == "not_set"
    assert statuses["infrastructure.compensation_scope"] == "checked"


def test_constraints_report_marks_an_unlimited_water_source_as_waived(
    tmp_path,
) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    constraints = Constraints(infrastructure={"water_supply_unlimited": True})
    workflow.verify(
        RunRequest("waived", sample_schedule(), constraints=constraints),
        lambda _s, _o: ReportedVerification(
            True, 1.0, constrained_report(constraints)
        ),
    )

    document = constraints_report_of(tmp_path / "runs" / "waived")
    statuses = {item["constraint"]: item["status"] for item in document["checks"]}
    assert statuses["infrastructure.water_supply"] == "waived"


def test_missing_dynamic_report_gives_a_reason_not_an_empty_list(tmp_path) -> None:
    workflow = RunWorkflow(tmp_path / "runs")
    constraints = sample_constraints()
    workflow.verify(
        RunRequest("no-dynamics", sample_schedule(), constraints=constraints),
        lambda _s, _o: ReportedVerification(False, None, None),
    )

    document = constraints_report_of(tmp_path / "runs" / "no-dynamics")
    assert document["checks"] is None
    assert isinstance(document["unavailable_reason"], str)
    assert document["unavailable_reason"]
    assert document["constraints_hash"] == constraints_hash(constraints)


def test_constraints_report_reaches_the_submission_package(tmp_path) -> None:
    workflow, model_dir = prepare_submittable_run(tmp_path, "packaged")

    report = workflow.submit("packaged", model_dir)

    assert (report.directory / "validation" / "constraints_report.json").is_file()
