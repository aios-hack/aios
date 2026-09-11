
from __future__ import annotations

from backend.contexts.showcase.application.notices import (
    notice_fields,
)

from pathlib import Path

from backend.contexts.optimization.application.verification_run import LAMBDA, _load_constraints
from backend.contexts.optimization.application.opm_active_calibration import WaterFamilyNpvCalibration
from backend.core.contracts import FinalNpvArtifact, RunArtifact
from backend.contexts.connectivity.domain.groups import GroupingParams, build_groups
from backend.contexts.connectivity.domain.measure import load_lambda
from backend.domain.economics import analyze_base_case, load_response_artifact
from backend.domain.schedule import parse_schedule
from backend.shared.resources import chdd_python_dir, model_z_dir
from backend.contexts.showcase.infrastructure.artifact_io import dump_bundle, load_schedule_json
from backend.contexts.showcase.application.build_showcase import (
    BASE_ID,
    SCENARIO_KINDS,
    confirmed_base_robustness,
    export_scenario,
)
from backend.contexts.showcase.application.scenarios import (
    ScenarioRobustness,
    export_scenarios_json,
)
from backend.contexts.optimization.application.environment import load_environment
from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
from backend.shared.json_io import read_json

CHAMPION = Path("config/opm-champion.json")
OUT = Path("frontend/public/data")
SCENARIO_ID = "policy-plan"


def main() -> int:
    champion = read_json(CHAMPION)
    observation_dir = Path(champion["observation_dir"])
    observation = read_json(observation_dir / 'observation.json')
    summary = read_json(observation_dir / 'final-npv-summary.json')
    schedule = load_schedule_json(observation_dir / "schedule.json")
    response = load_response_artifact(observation_dir / "response.json")
    if observation["canonical_schedule_hash"] != champion["canonical_schedule_hash"]:
        raise RuntimeError("champion pointer and persisted observation hash differ")
    if not observation["sound"] or not champion["sound"]:
        raise RuntimeError("an unsound observation cannot be exported as champion")

    runtime = resolve_runtime_artifacts()
    constraints = _load_constraints()
    model_dir = model_z_dir()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=Path("data/base_case/response.json"),
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
    )
    if env.npv_head is None:
        raise RuntimeError("champion export requires the economic head")
    calibration = WaterFamilyNpvCalibration.load(
        Path("config/opm-active-npv-calibration.json"),
        economic_model_version=env.npv_head.version,
    )
    calibrated = calibration.predict(champion["raw_surrogate_npv_rub"])
    if not calibrated.trusted or calibrated.npv_rub is None:
        raise RuntimeError("champion is outside active-calibration support")
    if abs(calibrated.npv_rub - champion["active_calibrated_npv_rub"]) > 0.01:
        raise RuntimeError("champion and active-calibration artifacts differ")
    parsed = parse_schedule((model_dir / "Model_Z_sch.inc").read_bytes())
    analysis = analyze_base_case(
        response,
        parsed.dates,
        parsed.t0_deck_date_index,
        env.normatives,
        env.policies,
    )
    if abs(analysis.npv_methodology - float(summary["npv_methodology"])) > 0.01:
        raise RuntimeError("persisted and reconstructed OPM economics differ")

    final_npv = FinalNpvArtifact(
        npv_table=analysis.table,
        npv_methodology=analysis.npv_methodology,
        source_run_id=summary["source_run_id"],
        source_response_hash=summary["source_response_hash"],
        economics_config_hash=summary["economics_config_hash"],
        methodology_version_hash=summary["methodology_version_hash"],
    )
    influence = load_lambda(LAMBDA)
    groups, _ = build_groups(
        influence, GroupingParams(), extra_wells=schedule.meta.wells
    )
    artifact = RunArtifact(
        config_hash=summary["economics_config_hash"],
        schedule=schedule,
        state_at_date=response.state_at_date,
        interval_response=response.interval_response,
        npv_table=analysis.table,
        trace=(),
        groups=groups,
        lambda_=influence,
        constraints=constraints,
        converged=True,
        self_consistent=True,
        final_npv=final_npv,
    )
    meta = {
        "provenance": "opm-confirmed-water-feedback-champion",
        "synthetic": False,
        "prediction": False,
        "opm_confirmed": True,
        "sound": True,
        "canonical_schedule_hash": champion["canonical_schedule_hash"],
        "source_run_id": summary["source_run_id"],
        "response_hash": response.response_hash,
        "raw_surrogate_npv_rub": champion["raw_surrogate_npv_rub"],
        "active_calibrated_npv_rub": calibrated.npv_rub,
        "active_calibration_version": calibration.version,
        "active_calibration_blind_holdout_absolute_relative_error": (
            calibration.blind_holdout_absolute_relative_error
        ),
        "active_calibration_blind_extension_absolute_relative_error": (
            calibration.blind_extension_absolute_relative_error
        ),
        "economic_ood_score": champion["economic_ood_score"],
        "economic_ood_threshold": champion["economic_ood_threshold"],
        "opm_npv_rub": champion["opm_npv_rub"],
        "water": champion["water"],
        **notice_fields("showcase.notice.champion"),
    }
    written = export_scenario(
        artifact,
        OUT / SCENARIO_ID,
        {kind: dict(meta, kind=kind) for kind in SCENARIO_KINDS},
    )
    bundle = OUT / "bundles" / f"{SCENARIO_ID}.json"
    dump_bundle(artifact, bundle)
    written.append(bundle)
    base_npv = read_json(OUT / BASE_ID / 'npv.json')
    written.append(
        export_scenarios_json(
            [
                OUT / "bundles" / "base.json",
                OUT / "bundles" / "whatif-injection-cut.json",
                bundle,
            ],
            OUT / "scenarios.json",
            {
                BASE_ID: confirmed_base_robustness(
                    float(base_npv["npv_methodology"]),
                    base_npv["meta"]["source_run_id"],
                ),
                SCENARIO_ID: ScenarioRobustness(
                    ood_score=champion["economic_ood_score"],
                    ood_threshold=champion["economic_ood_threshold"],
                    final_npv_rub=champion["opm_npv_rub"],
                    final_npv_run_id=summary["source_run_id"],
                    predicted_npv_rub=champion["raw_surrogate_npv_rub"],
                    calibrated_npv_rub=calibrated.npv_rub,
                    run_validation_clean=True,
                )
            },
        )
    )
    for path in written:
        print(path)
    print(
        f"champion {champion['canonical_schedule_hash'][:12]}: "
        f"OPM={champion['opm_npv_rub'] / 1e9:.3f} млрд, "
        f"raw={champion['raw_surrogate_npv_rub'] / 1e9:.3f} млрд, "
        f"OOD={champion['economic_ood_score']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
