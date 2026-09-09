"""Local warm-start adaptation with historical replay and scenario-level splits.

Research checkpoints only: never updates the production manifest or OOD gate.
The local test label has been inspected historically, so this is not a blind test.
"""
import argparse
import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import torch

from backend.application.optimization.runtime_artifacts import resolve_runtime_artifacts
from backend.core.contracts import canonical_bytes, hash_schedule
from backend.domain.economics import load_response_artifact
from backend.ml.surrogate.features import ScheduleFeatureizer
from backend.ml.surrogate.model import (
    TrajectorySurrogate, TrainingExample, _example_tensors, _legacy_checkpoint_modules,
    _elementwise_loss,
)
from backend.ml.surrogate.model_z_context import ModelZFeatureArtifact
from backend.presentation.cli.run import load_run_request


def sample_scenarios(tensors, counts, indices, width):
    starts = [0]
    for count in counts:
        starts.append(starts[-1] + count)
    chunks = [tuple(t[starts[i]:starts[i + 1]].clone() for t in tensors) for i in indices]
    return (torch.cat([c[0][:, :width] for c in chunks]),
            torch.cat([c[1] for c in chunks]), torch.cat([c[2] for c in chunks]))


def combine(chunks):
    return tuple(torch.cat([chunk[i] for chunk in chunks]) for i in range(3))


def ensure_disjoint_splits(train_hashes, validation_hashes, test_hashes):
    train, validation, test = map(set, (train_hashes, validation_hashes, test_hashes))
    if train & validation or train & test or validation & test:
        raise ValueError("scenario leakage across training, validation, and test")


def scaled(model, chunk):
    x, wells, y = chunk
    return model.input_scaler.transform(x), wells, model.target_scaler.transform(y)


def errors(model, chunk):
    x, wells, truth = scaled(model, chunk)
    total, real, n = 0., torch.zeros(6), 0
    with torch.inference_mode():
        for start in range(0, len(x), 32768):
            estimate = model.network(x[start:start + 32768], wells[start:start + 32768])
            actual = truth[start:start + 32768]
            total += float(_elementwise_loss(estimate, actual, model.config).sum())
            real += (torch.expm1(model.target_scaler.inverse(estimate)).clamp_min(0) -
                     torch.expm1(model.target_scaler.inverse(actual)).clamp_min(0)).abs().sum(0)
            n += len(actual)
    return {"loss": total / (n * 6), "raw_network_channel_mae": (real / n).tolist(), "nodes": n}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--replay-scenarios", type=int, default=49)
    parser.add_argument("--validation-scenarios", type=int, default=10)
    parser.add_argument("--members", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--learning-rates", type=float, nargs="+", default=[1e-4, 3e-5])
    args = parser.parse_args(argv)
    if args.out.exists() or min(args.threads, args.epochs, args.replay_scenarios, args.validation_scenarios) < 1:
        parser.error("new output directory and positive budgets required")
    import math
    if any(not math.isfinite(lr) or lr <= 0 for lr in args.learning_rates):
        parser.error("learning rates must be finite and positive")
    if len(set(args.members)) != len(args.members) or len(set(args.learning_rates)) != len(args.learning_rates):
        parser.error("duplicate arms are not allowed")
    args.out.mkdir(parents=True)
    torch.set_num_threads(args.threads)
    artifacts = resolve_runtime_artifacts()
    context = ModelZFeatureArtifact.load(artifacts.feature_context)
    manifest = json.loads(artifacts.checkpoint.read_text())
    members = [(artifacts.checkpoint.parent / path).resolve() for path in manifest["members"]]
    if any(i < 0 or i >= len(members) for i in args.members):
        parser.error("unknown ensemble member")
    reference = TrajectorySurrogate.load(members[0])
    if reference.config.target_parameterization != "absolute" or reference.config.scenario_context:
        parser.error("this replay experiment requires base-feature absolute checkpoints")
    width = len(reference.input_scaler.mean)
    with _legacy_checkpoint_modules():
        blob = torch.load(args.tensors, mmap=True, weights_only=False)
    if blob["dataset_hash"] != context.dataset_hash or tuple(blob["wells"]) != reference.wells:
        parser.error("replay tensor context or well axes differ from checkpoint")
    if args.replay_scenarios > len(blob["counts"]["train"]):
        parser.error("not enough replay scenarios")
    if args.validation_scenarios > len(blob["counts"]["validation"]):
        parser.error("not enough validation scenarios")
    stride = len(blob["counts"]["train"]) / args.replay_scenarios
    replay_ids = [int(i * stride) for i in range(args.replay_scenarios)]
    old = sample_scenarios(blob["tensors"]["train"], blob["counts"]["train"], replay_ids, width)
    old_validation = sample_scenarios(blob["tensors"]["validation"], blob["counts"]["validation"], list(range(args.validation_scenarios)), width)
    old_validation_counts = blob["counts"]["validation"][:args.validation_scenarios]
    identities = {"replay_train": [blob["identities"]["train"][i] for i in replay_ids],
                  "replay_validation": blob["identities"]["validation"][:args.validation_scenarios],
                  "local_train": ["candidate-004", "candidate-005", "candidate-006", "candidate-007"],
                  "local_validation": ["candidate-008"], "local_test": ["candidate-009"]}
    # Hold test tensors and labels closed until all arm selection is finished.
    featureizer = ScheduleFeatureizer()
    local = {}
    for run_id in identities["local_train"] + identities["local_validation"]:
        request = load_run_request(args.runs_root, run_id)
        response_path = args.runs_root / run_id / "response.json"
        response = load_response_artifact(response_path)
        model_input = replace(featureizer.transform(request.schedule, context.context), lambda_edges=())
        local[run_id] = _example_tensors([TrainingExample(model_input, response)], reference.wells)
        identities[run_id] = {"schedule_hash": hash_schedule(request.schedule),
                              "response_file_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest()}
        print(f"prepared {run_id}: {len(local[run_id][0])} nodes", flush=True)
    test_request = load_run_request(args.runs_root, "candidate-009")
    identities["candidate-009"] = {"schedule_hash": hash_schedule(test_request.schedule)}
    ensure_disjoint_splits(
        [row["canonical_schedule_hash"] for row in identities["replay_train"]]
        + [identities[k]["schedule_hash"] for k in identities["local_train"]],
        [row["canonical_schedule_hash"] for row in identities["replay_validation"]]
        + [identities[k]["schedule_hash"] for k in identities["local_validation"]],
        [identities["candidate-009"]["schedule_hash"]]
        + [row["canonical_schedule_hash"] for row in blob["identities"]["test"]],
    )
    train = combine([old] + [local[k] for _ in range(4) for k in identities["local_train"]])
    validation = combine([old_validation] + [local["candidate-008"] for _ in range(4)])
    validation_counts = list(old_validation_counts) + [len(local["candidate-008"][0])] * 4
    identities["local_train_repetitions"] = 4
    identities["local_validation_weight_repetitions"] = 4
    identities["test_warning"] = "held out from gradient and selection, but historically inspected; not a blind test"
    dataset_hash = hashlib.sha256(canonical_bytes(identities)).hexdigest()
    (args.out / "split.json").write_text(json.dumps(identities, indent=2) + "\n")
    print(f"train={len(train[0]):,}, validation={len(validation[0]):,}, CPU threads={args.threads}", flush=True)
    results = []
    for member_index, path in enumerate(members):
        if member_index not in args.members:
            continue
        for lr in args.learning_rates:
            arm = f"member-{member_index}-lr-{lr:g}"
            directory = args.out / arm
            directory.mkdir()
            model = TrajectorySurrogate.load(path)
            if len(model.input_scaler.mean) != width or model.config.target_parameterization != "absolute":
                raise ValueError("member architecture differs from replay features")
            before = errors(model, validation)
            initial_version = model.version
            model.config = replace(model.config, learning_rate=lr, max_epochs=args.epochs,
                                   patience=8, ranking_loss_weight=0, select_by="loss", lr_schedule="cosine")
            model.dataset_hash = dataset_hash
            torch.manual_seed(model.config.seed)
            began = time.perf_counter()
            print(f"START {arm} baseline validation loss={before['loss']:.6g}", flush=True)
            def on_epoch(item):
                print(json.dumps({"arm": arm, **asdict(item)}), flush=True)
            result = TrajectorySurrogate.fit_tensors(model, train=scaled(model, train),
                validation=scaled(model, validation), validation_node_counts=validation_counts,
                dataset_hash=dataset_hash, device="cpu", epoch_callback=on_epoch)
            after = errors(result.model, validation)
            result.model.save(directory / "model.pt")
            record = {"arm": arm, "initial_version": initial_version,
                      "model_version": result.model.version, "before": before, "after": after,
                      "local_validation": errors(result.model, local["candidate-008"]),
                      "replay_validation": errors(result.model, old_validation),
                      "epochs": len(result.history), "best_epoch": result.best_epoch,
                      "seconds": time.perf_counter() - began}
            (directory / "report.json").write_text(json.dumps(record, indent=2) + "\n")
            results.append(record)
            (args.out / "leaderboard.json").write_text(json.dumps(results, indent=2) + "\n")
            print(f"FINISHED {arm}: {before['loss']:.6g} -> {after['loss']:.6g}", flush=True)
    winner = min(results, key=lambda r: r["after"]["loss"])
    selected = TrajectorySurrogate.load(args.out / winner["arm"] / "model.pt")
    request = load_run_request(args.runs_root, "candidate-009")
    response = load_response_artifact(args.runs_root / "candidate-009/response.json")
    model_input = replace(featureizer.transform(request.schedule, context.context), lambda_edges=())
    test = _example_tensors([TrainingExample(model_input, response)], selected.wells)
    final = {"winner": winner, "test": errors(selected, test),
             "parent_test": errors(TrajectorySurrogate.load(members[int(winner['arm'].split('-')[1])]), test),
             "warning": "Research only. OOD bounds retained conservatively; production manifest unchanged."}
    (args.out / "result.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps(final, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
