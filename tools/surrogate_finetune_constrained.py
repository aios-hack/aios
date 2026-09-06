"""Локальный fine-tune trajectory ensemble на новых constrained OPM-метках.

Кандидат сохраняется отдельно и не продвигается в production manifest без
независимого holdout-гейта. Финальный water-feasible план используется только
как validation; zero-injection — как дополнительный test, не как train.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from contracts import canonical_bytes, hash_schedule
from economics import load_response_artifact
from optimizer.runtime_artifacts import resolve_runtime_artifacts
from optimizer.schedule_search import load_environment
from optimizer.search_run import (
    CONSTRAINTS_PATH,
    LAMBDA,
    MODEL_DIR,
    NORMATIVES,
    OOD_THRESHOLD,
    RESPONSE,
)
from surrogate.ensemble import TrajectoryEnsemble
from surrogate.features import ScheduleFeatureizer
from surrogate.model import (
    TrainingExample,
    _example_tensors,
    TrajectorySurrogate,
    target_mae,
)
from ui.artifact_io import _load_schedule
from ui.scenarios import load_constraints_file

OUT = Path("data/model-constrained-20260830")

SPECS = (
    ("smoke", Path("data/constrained-opm-smoke")),
    ("iter2", Path("data/constrained-opm-iter2")),
    ("feasible1", Path("data/constrained-opm-feasible1")),
    ("feasible2", Path("data/constrained-opm-feasible2")),
    ("external105", Path("data/constrained-opm-external105")),
    ("external105_safe", Path("data/constrained-opm-external105-safe")),
    ("final", Path("data/constrained-opm-feasible-final")),
    ("zero", Path("data/constrained-opm-zero")),
)


def main() -> int:
    constraints = load_constraints_file(
        CONSTRAINTS_PATH, require_water_supply=True
    )
    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=MODEL_DIR,
        normatives_path=NORMATIVES,
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
        ood_threshold=OOD_THRESHOLD,
        constraints=constraints,
    )
    featureizer = ScheduleFeatureizer()

    examples: dict[str, TrainingExample] = {}
    actual_npv = {}
    response_hashes = []
    for name, run_dir in SPECS:
        schedule = _load_schedule(
            json.loads((run_dir / "schedule.json").read_text(encoding="utf-8"))
        )
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        if result["canonical_schedule_hash"] != hash_schedule(schedule):
            raise ValueError(f"{name}: реконструирован другой schedule")
        response = load_response_artifact(run_dir / "response.json")
        model_input = replace(
            featureizer.transform(schedule, env.feature_context.context),
            lambda_edges=(),
        )
        example = TrainingExample(input=model_input, response=response)
        examples[name] = example
        actual_npv[name] = float(result["npv_opm"])
        response_hashes.append(response.response_hash)

    train_names = (
        "smoke",
        "iter2",
        "feasible1",
        "feasible2",
        "external105",
        "external105_safe",
    )
    validation_names = ("final",)
    test_names = ("zero",)
    train = tuple(examples[name] for name in train_names)
    validation = tuple(examples[name] for name in validation_names)
    test = tuple(examples[name] for name in test_names)
    dataset_hash = hashlib.sha256(
        canonical_bytes(
            {
                "base_dataset_hash": env.model.dataset_hash,
                "response_hashes": response_hashes,
                "train": train_names,
                "validation": validation_names,
                "test": test_names,
            }
        )
    ).hexdigest()

    OUT.mkdir(parents=True, exist_ok=True)
    checkpoints = []
    member_reports = []
    old_ensemble = env.model
    production_ensemble_version = old_ensemble.version
    for index, model in enumerate(old_ensemble.models):
        old_validation_mae = target_mae(model, validation)
        old_test_mae = target_mae(model, test)
        settings = replace(
            model.config,
            learning_rate=1.0e-5,
            max_epochs=80,
            patience=12,
            batch_size=32768,
            lr_schedule="none",
            ranking_loss_weight=0.0,
            money_rub_per_unit=(),
            select_by="loss",
        )
        model.config = settings
        parameterization = dict(
            parameterization=settings.target_parameterization,
            oil_density_t_per_m3=settings.oil_density_t_per_m3,
            scenario_context=settings.scenario_context,
        )
        train_x, train_wells, train_y = _example_tensors(
            train, model.wells, **parameterization
        )
        val_x, val_wells, val_y = _example_tensors(
            validation, model.wells, **parameterization
        )
        result = TrajectorySurrogate.fit_tensors(
            model,
            train=(
                model.input_scaler.transform(train_x),
                train_wells,
                model.target_scaler.transform(train_y),
            ),
            validation=(
                model.input_scaler.transform(val_x),
                val_wells,
                model.target_scaler.transform(val_y),
            ),
            validation_node_counts=tuple(len(item.input.nodes) for item in validation),
            train_node_counts=tuple(len(item.input.nodes) for item in train),
            dataset_hash=dataset_hash,
            epoch_callback=lambda item, member=index: print(
                json.dumps({"member": member, **asdict(item)}), flush=True
            ),
        )
        # fit_tensors deliberately leaves metadata ownership to its caller.
        result.model.dataset_hash = dataset_hash
        result.model.version = result.model._fingerprint()
        member_dir = OUT / f"member-{index}"
        checkpoint = result.model.save(member_dir / "model.pt")
        checkpoints.append(checkpoint)
        member_reports.append(
            {
                "member": index,
                "best_epoch": result.best_epoch,
                "old_validation_mae": old_validation_mae,
                "new_validation_mae": target_mae(result.model, validation),
                "old_test_mae": old_test_mae,
                "new_test_mae": target_mae(result.model, test),
            }
        )

    candidate = TrajectoryEnsemble.write_manifest(
        tuple(checkpoints), old_ensemble.weights, OUT / "trajectory_ensemble.json"
    )
    report = {
        "format": "aios.constrained-finetune-report.v1",
        "dataset_hash": dataset_hash,
        "production_ensemble_version": production_ensemble_version,
        "candidate_ensemble_version": candidate.version,
        "split": {
            "train": train_names,
            "validation": validation_names,
            "test": test_names,
        },
        "actual_npv": actual_npv,
        "members": member_reports,
        "promotion": {
            "approved": False,
            "reason": "eight local constrained runs are insufficient for production promotion",
        },
    }
    (OUT / "training_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
