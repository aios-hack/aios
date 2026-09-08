"""Train a production surrogate checkpoint from versioned tensor artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import torch
from backend.ml.surrogate.model import _legacy_checkpoint_modules

from backend.domain.economics import load_normatives
from torch import Tensor

from backend.ml.surrogate.model import (
    ModelConfig,
    Standardizer,
    TrajectorySurrogate,
    _NodeNetwork,
)
from backend.ml.surrogate.train import money_rub_per_unit
from backend.ml.surrogate.npv_target import validate_target_provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("rank", "physical"), required=True)
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--patience", type=int, default=None)
    parser.add_argument("--ranking-loss-weight", type=float, default=3.0)
    parser.add_argument("--ranking-target", choices=("exact-npv", "proxy"), default="exact-npv")
    parser.add_argument("--npv-labels", type=Path, default=Path("data/npv-v4/historical_labels_rebuilt.json"))
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--residual", action="store_true")
    parser.add_argument("--lr-schedule", choices=("none", "cosine"), default="none")
    parser.add_argument(
        "--scenario-fraction",
        type=float,
        default=1.0,
        help="доля обучающих сценариев (не узлов): 0.5 берёт каждый второй. "
             "Нужна там, где памяти не хватает на полный train; сравнивать "
             "модели допустимо только при одинаковой доле",
    )
    parser.add_argument(
        "--target-parameterization",
        choices=("absolute", "watercut"),
        default=None,
        help="по умолчанию берётся из тензоров: у контрактного набора целей "
             "формат отличается, и молча учить absolute на watercut-целях "
             "нельзя — каналы разные",
    )
    return parser


def _exact_targets(blob: dict, labels: dict) -> dict[str, Tensor]:
    if labels.get("format") != "aios.surrogate-npv-labels.v1" or labels.get("dataset_hash") != blob["dataset_hash"]:
        raise RuntimeError("метки ЧДД относятся к другому датасету")
    validate_target_provenance(labels.get("target_provenance"))
    train_hashes = {row["canonical_schedule_hash"] for row in blob["identities"]["train"]}
    validation_hashes = {row["canonical_schedule_hash"] for row in blob["identities"]["validation"]}
    if train_hashes & validation_hashes:
        raise RuntimeError("train и validation содержат одинаковые расписания")
    by_identity = {}
    for row in labels["rows"].values():
        key = (row["source_dataset"], row["scenario_id"], row["canonical_schedule_hash"])
        if key in by_identity:
            raise RuntimeError(f"дублирующаяся метка ЧДД: {key}")
        by_identity[key] = row
    result = {}
    for bucket in ("train", "validation"):
        values = []
        for identity in blob["identities"][bucket]:
            key = (identity["source_dataset"], identity["scenario_id"], identity["canonical_schedule_hash"])
            row = by_identity.get(key)
            if row is None or row["bucket"] != bucket:
                raise RuntimeError(f"нет метки ЧДД в правильном сплите: {key}")
            values.append(row["npv_rub"])
        result[bucket] = torch.tensor(values, dtype=torch.float64)
        if not bool(torch.isfinite(result[bucket]).all()):
            raise RuntimeError("нечисловая метка ЧДД")
    return result


def _config(args, rub_per_unit: tuple[float, ...]) -> ModelConfig:
    if args.mode == "rank":
        return ModelConfig(
            hidden_width=128,
            hidden_layers=3,
            batch_size=32768,
            max_epochs=args.epochs or 600,
            patience=args.patience or 100,
            seed=args.seed,
            scenario_context="mean",
            ranking_loss_weight=args.ranking_loss_weight,
            ranking_top_weighted=False,
            money_rub_per_unit=rub_per_unit,
            money_weight_alpha=0.0,
            select_by="rank",
            residual=args.residual,
            lr_schedule=args.lr_schedule,
        )
    return ModelConfig(
        hidden_width=128,
        hidden_layers=3,
        batch_size=32768,
        learning_rate=5.0e-4,
        max_epochs=args.epochs or 200,
        patience=args.patience or 30,
        seed=args.seed,
        scenario_context=False,
        ranking_loss_weight=0.0,
        money_rub_per_unit=(),
        select_by="loss",
        residual=args.residual,
        lr_schedule=args.lr_schedule,
    )


def main() -> int:
    args = _parser().parse_args()
    if args.threads < 1:
        raise RuntimeError("--threads должен быть положительным")
    torch.set_num_threads(args.threads)
    if (args.output_dir / "model.pt").exists():
        raise FileExistsError("output-dir уже содержит модель; выберите новый каталог")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"загрузка {args.tensors}", flush=True)
    # `mmap=True` оставляет тензоры на диске: страницы подгружаются по мере
    # чтения и вытесняются под давлением, а не держат резидентно 2.7 ГБ.
    # Без этого прогон был убит нехваткой памяти трижды подряд.
    with _legacy_checkpoint_modules():
        blob = torch.load(args.tensors, weights_only=False, mmap=True)
    tensor_format = blob.get("format")
    if tensor_format not in (
        "aios.surrogate-tensors.v2",
        "aios.surrogate-tensors-watercut.v1",
    ):
        raise RuntimeError(f"неподдержанный tensor artifact: {tensor_format!r}")
    # Параметризация принадлежит целям, а не флагу командной строки: обучить
    # `absolute` на watercut-целях значит перепутать каналы молча.
    from_tensors = blob.get("target_parameterization", "absolute")
    parameterization = args.target_parameterization or from_tensors
    if parameterization != from_tensors:
        raise RuntimeError(
            f"тензоры содержат цели {from_tensors!r}, запрошено {parameterization!r}"
        )
    if blob.get("feature_context_training_scenarios", 0) < 400:
        raise RuntimeError("production train запрещён на пилотном feature context")
    tensors = blob["tensors"]
    counts = blob["counts"]
    # Обучению нужны train и validation; test лежит в том же артефакте и
    # занимает 2.4 млн узлов впустую. На 24 ГБ машины это не мелочь: прогон
    # был убит нехваткой памяти, когда рядом считал OPM.
    tensors.pop("test", None)
    npv_targets = {}
    labels_hash = None
    if args.mode == "rank" and args.ranking_target == "exact-npv":
        label_bytes = args.npv_labels.read_bytes()
        labels_hash = hashlib.sha256(label_bytes).hexdigest()
        labels = json.loads(label_bytes)
        npv_targets = _exact_targets(blob, labels)
        if labels["target_provenance"]["normatives_sha256"] != hashlib.sha256(args.normatives.read_bytes()).hexdigest():
            raise RuntimeError("нормативы меток ЧДД отличаются от нормативов обучения")
    rub = money_rub_per_unit(load_normatives(args.normatives))
    config = replace(_config(args, rub), target_parameterization=parameterization)
    print(f"параметризация целей: {parameterization}", flush=True)

    if not 0.0 < args.scenario_fraction <= 1.0:
        raise RuntimeError("--scenario-fraction должна лежать в (0, 1]")

    prepared = {}
    for bucket in ("train", "validation"):
        x, well_index, y = tensors[bucket]
        if bucket == "train" and args.scenario_fraction < 1.0:
            # Резать надо по сценариям, а не по узлам: половина узлов каждого
            # сценария — это не половина обучающей выборки, а 490 покалеченных
            # траекторий. Единица сплита здесь такая же, как везде.
            n_scenarios = len(blob["identities"][bucket])
            per = len(x) // n_scenarios
            keep = max(1, int(round(n_scenarios * args.scenario_fraction)))
            step = n_scenarios / keep
            picked = sorted({int(i * step) for i in range(keep)})
            index = torch.cat(
                [torch.arange(s * per, (s + 1) * per) for s in picked]
            )
            x, well_index, y = x[index], well_index[index], y[index]
            counts[bucket] = [counts[bucket][s] for s in picked]
            blob["identities"][bucket] = [blob["identities"][bucket][s] for s in picked]
            if bucket in npv_targets:
                npv_targets[bucket] = npv_targets[bucket][picked]
            print(
                f"train урезан до {len(picked)} сценариев из {n_scenarios} "
                f"(доля {args.scenario_fraction})",
                flush=True,
            )
        if args.mode == "physical":
            if x.shape[1] % 2:
                raise RuntimeError("mean scenario context не делится на base/context")
            x = x[:, : x.shape[1] // 2]
        prepared[bucket] = (x, well_index, y)
        print(f"{bucket}: {x.shape[0]:,} узлов, {x.shape[1]} признаков", flush=True)

    torch.manual_seed(config.seed)
    model = TrajectorySurrogate(
        config=config,
        wells=blob["wells"],
        static_feature_names=blob["static_names"],
        input_scaler=Standardizer.fit(prepared["train"][0]),
        target_scaler=Standardizer.fit(prepared["train"][2]),
        domain=blob["domain"],
        network=_NodeNetwork(
            prepared["train"][0].shape[1], len(blob["wells"]), config
        ),
        dataset_hash=blob["dataset_hash"],
    )
    # Источник лежит в mmap, поэтому резидентной остаётся только
    # отмасштабированная копия: сырые страницы читаются один раз и
    # вытесняются. Масштабирование намеренно не in-place — писать в mmap
    # значило бы менять артефакт на диске.
    scaled = {}
    for bucket in list(prepared):
        x, well_index, y = prepared.pop(bucket)
        scaled[bucket] = (
            model.input_scaler.transform(x),
            well_index.clone(),
            model.target_scaler.transform(y),
        )
    tensors.clear()
    started = time.monotonic()

    def on_epoch(item) -> None:
        if item.epoch == 1 or item.epoch % 10 == 0:
            print(
                json.dumps(
                    {
                        "epoch": item.epoch,
                        "train_loss": item.train_loss,
                        "validation_loss": item.validation_loss,
                        "validation_rank": item.validation_rank,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    result = TrajectorySurrogate.fit_tensors(
        model,
        train=scaled["train"],
        validation=scaled["validation"],
        validation_node_counts=counts["validation"],
        train_node_counts=counts["train"] if args.mode == "rank" else None,
        dataset_hash=blob["dataset_hash"],
        device=args.device,
        epoch_callback=on_epoch,
        train_npv_rub=npv_targets.get("train"),
        validation_npv_rub=npv_targets.get("validation"),
    )
    checkpoint = result.model.save(args.output_dir / "model.pt")
    report = {
        "format": "aios.surrogate-tensor-training-report.v1",
        "mode": args.mode,
        "ranking_target": args.ranking_target if args.mode == "rank" else None,
        "ranking_sampling": "shared_well_step_coordinates",
        "npv_labels_sha256": labels_hash,
        "npv_labels": str(args.npv_labels) if labels_hash else None,
        "synthetic_inputs": False,
        "tensor_artifact": str(args.tensors),
        "feature_context": blob["feature_context"],
        "feature_context_training_scenarios": blob[
            "feature_context_training_scenarios"
        ],
        "dataset_hash": blob["dataset_hash"],
        "model_version": result.model.version,
        "checkpoint": checkpoint.name,
        "seed": config.seed,
        "config": asdict(config),
        "split": {bucket: len(counts[bucket]) for bucket in counts},
        "split_identity": blob["identities"],
        "best_epoch": result.best_epoch,
        "seconds": time.monotonic() - started,
        "history": [asdict(item) for item in result.history],
    }
    report_path = args.output_dir / "training_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        f"готово: {checkpoint}; best_epoch={result.best_epoch}; "
        f"version={result.model.version}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
