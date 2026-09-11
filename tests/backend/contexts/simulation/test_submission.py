from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.contexts.simulation.application.submission import SubmissionTractError, submit_schedule
from backend.contexts.simulation.infrastructure.cache import cache_key
from backend.contexts.reservoir.infrastructure.opm_deck import OpmDeckEmitter
from backend.contexts.simulation.infrastructure.runner import deck_hashes, summary_spec_hash
from backend.contexts.simulation.application.submission import _run
from backend.contexts.constraints.domain.schema import default_config, economics_config_hash
from backend.contexts.constraints.domain.config import (
    ArtifactHashes,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
)
from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    Schedule,
    ScheduleMeta,
)
from backend.contexts.runs.domain.run_result import FinalNpvArtifact, RunStatus
from backend.shared.hashing import hash_schedule
from backend.shared.paths import data_root
from backend.contexts.economics.domain.esp import ESP_CATALOG_2007
from backend.contexts.economics.domain.methodology_hash import methodology_version_hash
from backend.contexts.economics.application.base_case import analyze_base_case
from backend.contexts.schedule.domain.validate import ViolationKind
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.schedule.domain.build import deck_well_axis, initial_state_from_prefix
from backend.contexts.schedule.domain.canonical import canonical_part_hash
from backend.contexts.schedule.domain.validate_dynamic import _states_by_step

from tests.support.backend.environment import (
    docker_unavailable_reason,
    missing_reason,
    model_z_dir,
)

MODEL_Z = model_z_dir()
WORK_ROOT = data_root() / "base_run"
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"

pytestmark = [pytest.mark.skipif(MODEL_Z is None, reason=missing_reason('Model_Z directory')), pytest.mark.slow, pytest.mark.opm]

NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)

EXPECTED_DYNAMIC_COUNTS: dict[ViolationKind, int] = {
    ViolationKind.OPEN_WITHOUT_FLOW: 60,
    ViolationKind.BHP_LIMITED_WITHOUT_UNDERSHOOT: 12,
    ViolationKind.BHP_BELOW_PRODUCER_LIMIT: 1,
    ViolationKind.BHP_ABOVE_INJECTOR_LIMIT: 1,
}

EXPECTED_TOTAL_VIOLATIONS: int = sum(EXPECTED_DYNAMIC_COUNTS.values())

EXPECTED_BHP_LIMITED_WITHOUT_UNDERSHOOT: frozenset[tuple[int, str]] = frozenset(
    {
        (30, "77"),
        (39, "76"),
        (40, "65"),
        (40, "110"),
        (42, "81"),
        (71, "78"),
        (95, "82"),
        (103, "23"),
        (115, "101"),
        (131, "16"),
        (154, "106"),
        (190, "74"),
    }
)

EXPECTED_BHP_ABOVE_INJECTOR_LIMIT: frozenset[tuple[int, str]] = frozenset({(56, "94")})

EXPECTED_BHP_BELOW_PRODUCER_LIMIT: frozenset[tuple[int, str]] = frozenset({(13, "97")})


def _cached_response_entry() -> dict[str, object] | None:
    for path in (WORK_ROOT / "cache").glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            artifacts = tuple(Path(item) for item in entry["artifacts"])
        except (KeyError, TypeError, json.JSONDecodeError, OSError):
            continue
        names = {artifact.suffix.upper() for artifact in artifacts}
        if (
            entry.get("status") == RunStatus.OK.value
            and all(artifact.is_file() for artifact in artifacts)
            and {".SMSPEC", ".UNSMRY"} <= names
        ):
            return entry
    return None


def _submission_environment_unavailable_reason() -> str | None:
    if _cached_response_entry() is not None or docker_unavailable_reason() is None:
        return None
    return (
        "there is no usable cached response for the submission tract and "
        f"{docker_unavailable_reason()}"
    )


requires_submission_response = pytest.mark.skipif(
    _submission_environment_unavailable_reason() is not None,
    reason=(
        "submission tract acceptance requires a real response cache or Docker; "
        f"{_submission_environment_unavailable_reason()}"
    ),
)


def _hybrid_schedule() -> Schedule:
    raw = (MODEL_Z / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    wells = deck_well_axis(raw)
    initial_state = initial_state_from_prefix(parsed, wells)
    return Schedule(
        meta=ScheduleMeta(wells=wells, provenance="g6-submission-test"),
        initial_state=initial_state,
        fixed_deck_events=parsed.fixed_deck_events,
        control_events=parsed.control_events,
    )


def _seed_cache_entry_for(schedule: Schedule, tmp_path: Path) -> None:
    entry = _cached_response_entry()
    if entry is None:
        if docker_unavailable_reason() is not None:
            pytest.skip(_submission_environment_unavailable_reason())
        return

    emitter = OpmDeckEmitter(MODEL_Z)
    deck = emitter.emit(schedule, tmp_path / "scratch-deck")
    hashes = deck_hashes(deck, schedule)

    target_key = cache_key(hashes.deck_hash, hashes.canonical_schedule_hash, hashes.summary_hash)
    target_path = WORK_ROOT / "cache" / f"{target_key}.json"
    if target_path.exists():
        return
    entry["deck_hash"] = hashes.deck_hash
    entry["canonical_schedule_hash"] = hashes.canonical_schedule_hash
    entry["summary_hash"] = hashes.summary_hash
    target_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def _config(schedule: Schedule):
    emitter = OpmDeckEmitter(MODEL_Z)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        hashes = deck_hashes(deck, schedule)
        summary_hash = summary_spec_hash(deck.summary_plan.spec)
    artifact_hashes = ArtifactHashes(
        deck_hash=hashes.deck_hash,
        history_prefix_hash=canonical_part_hash(schedule.initial_state),
        summary_spec_hash=summary_hash,
        groups_hash="0" * 64,
        dataset_version_hash="0" * 64,
        surrogate_checkpoint_hash="0" * 64,
    )
    return default_config(NORMATIVES, artifact_hashes, global_seed=20260820)


@pytest.fixture(scope="module")
def schedule() -> Schedule:
    return _hybrid_schedule()


@pytest.fixture(scope="module")
def config(schedule):
    return _config(schedule)


@pytest.fixture(scope="module")
def run_and_response(schedule, config, tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("g6-seed")
    _seed_cache_entry_for(schedule, tmp)
    return _run(schedule, MODEL_Z, WORK_ROOT, use_cache=True)


def test_opm_run_status_is_ok(run_and_response) -> None:
    opm_run, _ = run_and_response
    assert opm_run.status is RunStatus.OK


def test_opm_run_canonical_schedule_hash_matches_recomputed(schedule, run_and_response) -> None:
    opm_run, _ = run_and_response
    assert opm_run.canonical_schedule_hash == hash_schedule(schedule)


def test_response_source_run_id_matches_opm_run(run_and_response) -> None:
    opm_run, response = run_and_response
    assert response.source_run_id == opm_run.run_id


def test_validate_static_gate_rejects_before_any_run(schedule, config) -> None:
    broken = Schedule(
        meta=schedule.meta,
        initial_state=schedule.initial_state,
        fixed_deck_events=schedule.fixed_deck_events,
        control_events=(
            ControlEvent(control_step=0, well="999", kind=EventKind.SET_LRAT, value=50.0),
        ),
    )
    with pytest.raises(SubmissionTractError, match="validate_static"):
        submit_schedule(broken, MODEL_Z, WORK_ROOT, config, use_cache=True)


@requires_submission_response
def test_dynamic_gate_rejects_the_real_baseline_over_well_71(schedule, config) -> None:
    with pytest.raises(SubmissionTractError, match="validate_dynamic") as excinfo:
        submit_schedule(schedule, MODEL_Z, WORK_ROOT, config, use_cache=True)
    assert f"{EXPECTED_TOTAL_VIOLATIONS} violations" in str(excinfo.value)


@pytest.fixture(scope="module")
def final_npv(schedule, config, run_and_response):
    opm_run, response = run_and_response
    raw = (MODEL_Z / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    analysis = analyze_base_case(
        response, parsed.dates, parsed.t0_deck_date_index, config.normatives, config.policies
    )
    return FinalNpvArtifact(
        npv_table=analysis.table,
        npv_methodology=analysis.table.npv_methodology,
        source_run_id=opm_run.run_id,
        source_response_hash=response.response_hash,
        economics_config_hash=economics_config_hash(config),
        methodology_version_hash=methodology_version_hash(),
    )


def test_final_npv_source_matches_run_and_response(final_npv, run_and_response) -> None:
    opm_run, response = run_and_response
    assert final_npv.source_run_id == opm_run.run_id
    assert final_npv.source_response_hash == response.response_hash


def test_final_npv_config_and_methodology_hashes_match_independent_recomputation(
    final_npv, config
) -> None:
    assert final_npv.economics_config_hash == economics_config_hash(config)
    assert final_npv.methodology_version_hash == methodology_version_hash()
    assert len(final_npv.economics_config_hash) == 64
    assert len(final_npv.methodology_version_hash) == 64


def test_final_npv_methodology_matches_its_own_table(final_npv) -> None:
    assert final_npv.npv_methodology == final_npv.npv_table.npv_methodology
    assert final_npv.npv_methodology > 0.0


@requires_submission_response
def test_all_six_identities_are_computed_even_when_the_tract_fails(schedule, config) -> None:
    result = submit_schedule(
        schedule, MODEL_Z, WORK_ROOT, config, use_cache=True, strict=False
    )

    names = [check.name for check in result.identities]
    assert names == [
        "run_schedule_hash",
        "run_status_ok",
        "response_source_run_id",
        "npv_source_provenance",
        "economics_config_hash",
        "methodology_version_hash",
    ]
    assert result.failed_identities == ()
    assert result.sound is False
    assert result.dynamic_report is not None and not result.dynamic_report.ok
    assert result.dynamic_report.counts() == EXPECTED_DYNAMIC_COUNTS
    assert {
        violation.control_step
        for violation in result.dynamic_report.by_kind()[ViolationKind.OPEN_WITHOUT_FLOW]
        if violation.well == "71"
    } == set(range(60))
    assert result.final_npv is not None
    with pytest.raises(SubmissionTractError, match="validate_dynamic"):
        _ = result.npv_methodology


@requires_submission_response
def test_bhp_violations_name_the_exact_wells_and_steps(schedule, config) -> None:
    result = submit_schedule(
        schedule, MODEL_Z, WORK_ROOT, config, use_cache=True, strict=False
    )
    assert result.dynamic_report is not None
    by_kind = result.dynamic_report.by_kind()

    def located(kind: ViolationKind) -> frozenset[tuple[int, str]]:
        return frozenset(
            (violation.control_step, violation.well) for violation in by_kind[kind]
        )

    assert (
        located(ViolationKind.BHP_LIMITED_WITHOUT_UNDERSHOOT)
        == EXPECTED_BHP_LIMITED_WITHOUT_UNDERSHOOT
    )
    assert (
        located(ViolationKind.BHP_ABOVE_INJECTOR_LIMIT)
        == EXPECTED_BHP_ABOVE_INJECTOR_LIMIT
    )
    assert (
        located(ViolationKind.BHP_BELOW_PRODUCER_LIMIT)
        == EXPECTED_BHP_BELOW_PRODUCER_LIMIT
    )


@requires_submission_response
def test_the_injector_overshoot_is_the_producer_to_injector_conversion_step(
    schedule, config
) -> None:
    result = submit_schedule(
        schedule, MODEL_Z, WORK_ROOT, config, use_cache=True, strict=False
    )
    assert result.response is not None and result.dynamic_report is not None

    states = _states_by_step(result.response.state_at_date)
    overshoot = states[(56, "94")]
    assert overshoot.bhp > 300.0
    assert overshoot.injection_rate > 0.0
    assert states[(55, "94")].injection_rate == 0.0
    assert states[(57, "94")].bhp <= 300.0


@requires_submission_response
def test_strict_mode_lists_every_reason_at_once(schedule, config) -> None:
    with pytest.raises(SubmissionTractError, match="link A §10.5 did not pass") as excinfo:
        submit_schedule(schedule, MODEL_Z, WORK_ROOT, config, use_cache=True)

    message = str(excinfo.value)
    assert f"validate_dynamic: {EXPECTED_TOTAL_VIOLATIONS} violations" in message
    assert "validate_dynamic was not run" not in message
