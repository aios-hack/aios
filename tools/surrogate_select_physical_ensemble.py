"""Select a physical trajectory ensemble on validation, then unlock test once."""

from __future__ import annotations

import argparse
import gc
import itertools
import json
import time
from pathlib import Path

import torch
from torch import Tensor
from torch.nn import functional

from surrogate.ensemble import TrajectoryEnsemble
from surrogate.model import TARGET_NAMES, TrajectorySurrogate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        action="append",
        required=True,
        help="repeat for every independently trained physical model",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    return parser


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _mask_physical(decoded: Tensor, x: Tensor) -> None:
    available = x[:, 15] > 0.5
    producer = x[:, 17] > 0.5
    injector = x[:, 18] > 0.5
    opened = x[:, 19] > 0.5
    active = available & opened
    decoded[~active, :5] = 0.0
    decoded[active & producer, 2] = 0.0
    decoded[active & producer, 4] = 0.0
    decoded[active & injector, 0] = 0.0
    decoded[active & injector, 1] = 0.0
    decoded[active & injector, 3] = 0.0


def _predict(model: TrajectorySurrogate, x: Tensor, well_index: Tensor, device: str) -> Tensor:
    if model.config.scenario_context:
        raise RuntimeError("physical ensemble ожидает model без scenario context")
    if model.config.target_parameterization != "absolute":
        raise RuntimeError("physical ensemble пока поддерживает absolute targets")
    if x.shape[1] % 2:
        raise RuntimeError("mean-context tensor имеет нечётную ширину")
    x = x[:, : x.shape[1] // 2]
    result = torch.empty((len(x), len(TARGET_NAMES)), dtype=torch.float32)
    model.network.to(device).eval()
    with torch.no_grad():
        for start in range(0, len(x), model.config.batch_size):
            stop = min(start + model.config.batch_size, len(x))
            source = x[start:stop]
            numeric = model.input_scaler.transform(source).to(device)
            indices = well_index[start:stop].to(device)
            standardized = model.network(numeric, indices).cpu()
            decoded = torch.expm1(model.target_scaler.inverse(standardized)).clamp_min_(0.0)
            _mask_physical(decoded, source)
            result[start:stop] = decoded
            if start == 0 or stop == len(x) or stop % (model.config.batch_size * 20) == 0:
                print(f"  nodes {stop:,}/{len(x):,}", flush=True)
    model.network.cpu()
    if device == "mps" and torch.backends.mps.is_available():
        torch.mps.empty_cache()
    return result


def _metrics(
    predicted: Tensor,
    actual_log: Tensor,
    counts: list[int],
    scaler,
) -> dict:
    actual = torch.expm1(actual_log)
    predicted_log = torch.log1p(predicted)
    standardized_predicted = scaler.transform(predicted_log)
    standardized_actual = scaler.transform(actual_log)
    channel_mae = (predicted - actual).abs().mean(dim=0)
    scenario_oil_errors = []
    offset = 0
    for count in counts:
        stop = offset + count
        scenario_oil_errors.append(
            abs(float(predicted[offset:stop, 0].sum() - actual[offset:stop, 0].sum()))
        )
        offset = stop
    if offset != len(predicted):
        raise RuntimeError("scenario counts не покрывают predictions")
    return {
        "standardized_smooth_l1": float(
            functional.smooth_l1_loss(
                standardized_predicted,
                standardized_actual,
                beta=0.1,
            )
        ),
        "channel_mae": {
            name: float(value) for name, value in zip(TARGET_NAMES, channel_mae)
        },
        "scenario_total_oil_mae": sum(scenario_oil_errors)
        / len(scenario_oil_errors),
    }


def _weight_candidates(n_models: int):
    for index in range(n_models):
        yield (index,), (1.0,)
    for members in itertools.combinations(range(n_models), 2):
        for first in (0.25, 0.5, 0.75):
            yield members, (first, 1.0 - first)
    for width in range(3, n_models + 1):
        for members in itertools.combinations(range(n_models), width):
            yield members, (1.0 / width,) * width
    if n_models == 3:
        for weights in (
            (0.5, 0.25, 0.25),
            (0.25, 0.5, 0.25),
            (0.25, 0.25, 0.5),
        ):
            yield (0, 1, 2), weights


def _weighted_prediction(
    predictions: list[Tensor], members: tuple[int, ...], weights: tuple[float, ...]
) -> Tensor:
    return sum(
        weight * predictions[index]
        for index, weight in zip(members, weights)
    )


def main() -> int:
    args = _parser().parse_args()
    if len(args.checkpoint) < 2:
        raise RuntimeError("для ensemble selection нужны хотя бы две модели")
    started = time.monotonic()
    blob = torch.load(
        args.tensors,
        map_location="cpu",
        weights_only=False,
        mmap=True,
    )
    if blob.get("format") != "aios.surrogate-tensors.v2":
        raise RuntimeError("неподдержанный tensor artifact")
    models = tuple(TrajectorySurrogate.load(path) for path in args.checkpoint)
    reference = models[0]
    for model in models[1:]:
        if model.dataset_hash != reference.dataset_hash:
            raise RuntimeError("physical checkpoints относятся к разным datasets")
        if model.target_scaler != reference.target_scaler:
            raise RuntimeError("target scalers физических моделей разошлись")

    validation_x, validation_well, validation_y = blob["tensors"]["validation"]
    predictions = []
    for index, model in enumerate(models):
        print(f"validation member {index + 1}/{len(models)}: {model.version}", flush=True)
        predictions.append(
            _predict(model, validation_x, validation_well, args.device)
        )
    candidates = []
    for members, weights in _weight_candidates(len(models)):
        predicted = _weighted_prediction(predictions, members, weights)
        metrics = _metrics(
            predicted,
            validation_y,
            blob["counts"]["validation"],
            reference.target_scaler,
        )
        candidates.append(
            {
                "members": members,
                "member_versions": [models[index].version for index in members],
                "weights": weights,
                "validation": metrics,
            }
        )
        print(
            f"members={members}, weights={weights}: "
            f"loss={metrics['standardized_smooth_l1']:.6f}; "
            f"oil={metrics['channel_mae']['oil_mass_delta']:.4f}; "
            f"scenario_oil={metrics['scenario_total_oil_mae']:.2f}",
            flush=True,
        )
    winner = min(
        candidates,
        key=lambda item: (
            item["validation"]["standardized_smooth_l1"],
            item["validation"]["scenario_total_oil_mae"],
            len(item["members"]),
            item["members"],
        ),
    )
    selection = {
        "format": "aios.physical-ensemble-selection.v1",
        "dataset_hash": reference.dataset_hash,
        "selection_data": ["validation"],
        "test_read_during_selection": False,
        "selection_metric": "standardized_smooth_l1",
        "checkpoints": [str(path) for path in args.checkpoint],
        "winner": winner,
        "candidates": candidates,
    }
    _write_json(args.output_dir / "selection_report.json", selection)
    print(f"LOCKED members={winner['members']}; test ещё не прочитан", flush=True)
    del predictions
    gc.collect()

    selected_indices = tuple(winner["members"])
    test_x, test_well, test_y = blob["tensors"]["test"]
    selected_predictions = []
    for index in selected_indices:
        print(f"test locked member {index}: {models[index].version}", flush=True)
        selected_predictions.append(
            _predict(models[index], test_x, test_well, args.device)
        )
    selected_weights = tuple(float(value) for value in winner["weights"])
    test_predicted = sum(
        weight * prediction
        for weight, prediction in zip(selected_weights, selected_predictions)
    )
    test_metrics = _metrics(
        test_predicted,
        test_y,
        blob["counts"]["test"],
        reference.target_scaler,
    )
    checkpoints = tuple(args.checkpoint[index] for index in selected_indices)
    ensemble = TrajectoryEnsemble.write_manifest(
        checkpoints,
        selected_weights,
        args.output_dir / "trajectory_ensemble.json",
    )
    report = {
        **selection,
        "format": "aios.physical-ensemble-training-report.v1",
        "test_metrics": test_metrics,
        "ensemble_version": ensemble.version,
        "manifest": "trajectory_ensemble.json",
        "seconds": time.monotonic() - started,
    }
    _write_json(args.output_dir / "training_report.json", report)
    print(
        f"TEST once: loss={test_metrics['standardized_smooth_l1']:.6f}; "
        f"oil={test_metrics['channel_mae']['oil_mass_delta']:.4f}; "
        f"scenario_oil={test_metrics['scenario_total_oil_mae']:.2f}",
        flush=True,
    )
    print(f"готово: ensemble={ensemble.version}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
