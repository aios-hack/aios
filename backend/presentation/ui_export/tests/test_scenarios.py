from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.contracts import Constraints, FinalNpvArtifact, RunArtifact, WellOutage

from backend.presentation.ui_export.artifact_io import dump_bundle
from backend.presentation.ui_export.fixtures import make_synthetic_artifact
from backend.presentation.ui_export.scenarios import (
    REGRET_PARTS,
    ScenarioRobustness,
    WorstRegret,
    build_scenario_index,
    constraints_from_json,
    constraints_to_json,
    export_scenarios_json,
)

ROBUSTNESS_FIELDS: tuple[str, ...] = (
    "ood_score",
    "ood_threshold",
    "worst_regret",
    "final_npv",
)


def _full_constraints() -> Constraints:
    return Constraints(
        injection_limits={2007: 5000.0, 2008: 5200.0},
        liquid_limits={2007: 8000.0},
        production_floors={2008: 40.0},
        watercut_limits={2008: 0.95},
        well_outages=(
            WellOutage(well="10", control_step_from=0, control_step_to=3),
            WellOutage(well="12", control_step_from=5, control_step_to=5),
        ),
        infrastructure={"kns_limit_m3_per_day": 12_000.0, "park": "T-1"},
    )


def test_round_trip_full_document() -> None:
    original = _full_constraints()
    document = constraints_to_json(original)
    assert constraints_from_json(document, n_intervals=224) == original


def test_round_trip_empty_document_stays_empty() -> None:
    empty = Constraints()
    document = constraints_to_json(empty)
    assert document == {
        "injection_limits": {},
        "liquid_limits": {},
        "production_floors": {},
        "watercut_limits": {},
        "well_outages": [],
        "infrastructure": {},
    }
    restored = constraints_from_json(document, n_intervals=224)
    assert restored == empty
    assert restored.injection_limits == {}
    assert restored.well_outages == ()


def test_year_keys_are_strings_in_json_and_ints_in_python() -> None:
    document = constraints_to_json(_full_constraints())
    assert all(isinstance(k, str) for k in document["injection_limits"])
    text = json.dumps(document, ensure_ascii=False)
    restored = constraints_from_json(json.loads(text), n_intervals=224)
    assert all(isinstance(k, int) for k in restored.injection_limits)
    assert restored.injection_limits[2007] == 5000.0


def test_watercut_in_percent_is_rejected() -> None:
    document = constraints_to_json(Constraints())
    document["watercut_limits"] = {"2008": 50.0}
    with pytest.raises(ValueError, match="долей 0..1"):
        constraints_from_json(document, n_intervals=224)


def test_watercut_at_bounds_is_accepted() -> None:
    document = constraints_to_json(Constraints())
    document["watercut_limits"] = {"2008": 1.0, "2009": 0.0}
    restored = constraints_from_json(document, n_intervals=224)
    assert restored.watercut_limits == {2008: 1.0, 2009: 0.0}


def test_negative_limit_is_rejected() -> None:
    document = constraints_to_json(Constraints())
    document["liquid_limits"] = {"2007": -1.0}
    with pytest.raises(ValueError, match="отрицательным"):
        constraints_from_json(document, n_intervals=224)


def test_non_integer_year_is_rejected() -> None:
    document = constraints_to_json(Constraints())
    document["injection_limits"] = {"две тысячи седьмой": 10.0}
    with pytest.raises(ValueError, match="целым числом"):
        constraints_from_json(document, n_intervals=224)


def test_outage_beyond_horizon_is_rejected() -> None:
    document = constraints_to_json(Constraints())
    document["well_outages"] = [
        {"well": "10", "control_step_from": 0, "control_step_to": 224}
    ]
    with pytest.raises(ValueError, match="вне горизонта"):
        constraints_from_json(document, n_intervals=224)


def test_outage_horizon_follows_n_intervals_parameter() -> None:
    document = constraints_to_json(Constraints())
    document["well_outages"] = [
        {"well": "10", "control_step_from": 0, "control_step_to": 5}
    ]
    assert constraints_from_json(document, n_intervals=6).well_outages[0].control_step_to == 5
    with pytest.raises(ValueError, match="вне горизонта"):
        constraints_from_json(document, n_intervals=5)


def test_outage_reversed_range_is_rejected() -> None:
    document = constraints_to_json(Constraints())
    document["well_outages"] = [
        {"well": "10", "control_step_from": 7, "control_step_to": 3}
    ]
    with pytest.raises(ValueError, match="больше control_step_to"):
        constraints_from_json(document, n_intervals=224)


def test_unknown_section_is_rejected_not_silently_dropped() -> None:
    document = constraints_to_json(Constraints())
    document["bhp_limits"] = {"2007": 50.0}
    with pytest.raises(ValueError, match="неизвестные разделы"):
        constraints_from_json(document, n_intervals=224)


def _rebuild(
    artifact: RunArtifact,
    *,
    constraints: Constraints | None = None,
    converged: bool | None = None,
    final_npv: FinalNpvArtifact | None = None,
) -> RunArtifact:
    return RunArtifact(
        config_hash=artifact.config_hash,
        schedule=artifact.schedule,
        state_at_date=artifact.state_at_date,
        interval_response=artifact.interval_response,
        npv_table=artifact.npv_table,
        trace=artifact.trace,
        groups=artifact.groups,
        lambda_=artifact.lambda_,
        constraints=artifact.constraints if constraints is None else constraints,
        converged=artifact.converged if converged is None else converged,
        self_consistent=artifact.self_consistent,
        final_npv=final_npv,
    )


def _write_artifact(path: Path, *, submitted: bool, converged: bool = True) -> Path:
    artifact = make_synthetic_artifact()
    final_npv = (
        FinalNpvArtifact(
            npv_table=artifact.npv_table,
            npv_methodology=artifact.npv_table.npv_methodology,
            source_run_id="run-1",
            source_response_hash="1" * 64,
            economics_config_hash="2" * 64,
            methodology_version_hash="3" * 64,
        )
        if submitted
        else None
    )
    dump_bundle(_rebuild(artifact, converged=converged, final_npv=final_npv), path)
    return path


def test_index_separates_submitted_from_what_if(tmp_path: Path) -> None:
    submitted = _write_artifact(tmp_path / "final.json", submitted=True)
    what_if = _write_artifact(tmp_path / "what_if.json", submitted=False)
    index = build_scenario_index([submitted, what_if])

    assert index["submitted"] == "final"
    by_id = {s["id"]: s for s in index["scenarios"]}
    assert by_id["final"]["is_submitted"] is True
    assert by_id["final"]["npv_methodology"] == 123_456_789.0
    assert by_id["what_if"]["is_submitted"] is False
    assert by_id["what_if"]["npv_methodology"] is None
    assert by_id["what_if"]["converged"] is True
    assert by_id["what_if"]["self_consistent"] is True
    assert len(by_id["final"]["config_hash"]) == 64


def test_two_submitted_scenarios_raise(tmp_path: Path) -> None:
    first = _write_artifact(tmp_path / "final_a.json", submitted=True)
    second = _write_artifact(tmp_path / "final_b.json", submitted=True)
    with pytest.raises(ValueError, match="более чем у одного сценария"):
        build_scenario_index([first, second])


def test_index_reports_not_converged_flag(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path / "diverged.json", submitted=False, converged=False)
    index = build_scenario_index([path])
    assert index["scenarios"][0]["converged"] is False
    assert index["submitted"] is None


def test_summary_counts_match_artifact_and_invent_no_numbers(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path / "what_if.json", submitted=False)
    artifact_constraints = make_synthetic_artifact().constraints
    summary = build_scenario_index([path])["scenarios"][0]["constraints"]

    assert summary["injection_limits"] == len(artifact_constraints.injection_limits)
    assert summary["liquid_limits"] == len(artifact_constraints.liquid_limits)
    assert summary["production_floors"] == len(artifact_constraints.production_floors)
    assert summary["watercut_limits"] == len(artifact_constraints.watercut_limits)
    assert summary["well_outages"] == len(artifact_constraints.well_outages)
    assert summary["infrastructure"] == len(artifact_constraints.infrastructure)
    assert summary["outage_wells"] == sorted({o.well for o in artifact_constraints.well_outages})
    assert summary["years"] == sorted(
        set(artifact_constraints.injection_limits)
        | set(artifact_constraints.liquid_limits)
        | set(artifact_constraints.production_floors)
        | set(artifact_constraints.watercut_limits)
    )
    assert summary["empty"] is False


def test_summary_of_empty_constraints_is_marked_empty(tmp_path: Path) -> None:
    bare = _rebuild(make_synthetic_artifact(), constraints=Constraints())
    path = tmp_path / "bare.json"
    dump_bundle(bare, path)
    summary = build_scenario_index([path])["scenarios"][0]["constraints"]
    assert summary["empty"] is True
    assert summary["years"] == []
    assert summary["well_outages"] == 0


def test_export_scenarios_json_writes_readable_index(tmp_path: Path) -> None:
    submitted = _write_artifact(tmp_path / "final.json", submitted=True)
    what_if = _write_artifact(tmp_path / "what_if.json", submitted=False)
    out = export_scenarios_json([submitted, what_if], tmp_path / "out" / "scenarios.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["submitted"] == "final"
    assert [s["id"] for s in data["scenarios"]] == ["final", "what_if"]


def test_robustness_fields_default_to_not_measured(tmp_path: Path) -> None:
    """F8: сценарий, о котором ничего не мерили, несёт четыре `null`.
    Отсутствия поля быть не должно — интерфейс отличает «не измерено» от
    «поля нет» только по наличию ключа."""

    path = _write_artifact(tmp_path / "what_if.json", submitted=False)
    entry = build_scenario_index([path])["scenarios"][0]
    for field in ROBUSTNESS_FIELDS:
        assert field in entry
        assert entry[field] is None


def test_measured_robustness_lands_in_the_entry(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path / "what_if.json", submitted=False)
    entry = build_scenario_index(
        [path],
        {
            "what_if": ScenarioRobustness(
                ood_score=0.18,
                ood_threshold=0.5,
                worst_regret=WorstRegret(
                    scenario_id="holdout-outage-and-injection-cap",
                    value_rub=201_000_000.0,
                    part="holdout",
                ),
            )
        },
    )["scenarios"][0]
    assert entry["ood_score"] == 0.18
    assert entry["ood_threshold"] == 0.5
    assert entry["worst_regret"] == {
        "scenario_id": "holdout-outage-and-injection-cap",
        "value_rub": 201_000_000.0,
        "part": "holdout",
    }
    assert entry["final_npv"] is None


def test_final_npv_is_a_number_together_with_its_run(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path / "final.json", submitted=True)
    entry = build_scenario_index(
        [path],
        {
            "final": ScenarioRobustness(
                final_npv_rub=10_786_000_000.0, final_npv_run_id="run-42"
            )
        },
    )["scenarios"][0]
    assert entry["final_npv"] == {"npv_rub": 10_786_000_000.0, "run_id": "run-42"}


def test_half_of_the_final_npv_pair_is_rejected() -> None:
    with pytest.raises(ValueError, match="половина пары"):
        ScenarioRobustness(final_npv_rub=1.0)
    with pytest.raises(ValueError, match="половина пары"):
        ScenarioRobustness(final_npv_run_id="run-42")


def test_ood_score_without_a_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="ood_threshold"):
        ScenarioRobustness(ood_score=0.18)


def test_unknown_battery_part_is_rejected() -> None:
    assert set(REGRET_PARTS) == {"optimization", "holdout"}
    with pytest.raises(ValueError, match="неизвестна"):
        WorstRegret(scenario_id="S-07", value_rub=1.0, part="dev")


def test_measured_zero_ood_is_not_the_same_as_not_measured(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path / "what_if.json", submitted=False)
    entry = build_scenario_index(
        [path], {"what_if": ScenarioRobustness(ood_score=0.0, ood_threshold=0.5)}
    )["scenarios"][0]
    assert entry["ood_score"] == 0.0
    assert entry["ood_score"] is not None
