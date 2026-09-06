"""Rebuild surrogate input tensors against a production feature context.

The expensive OPM targets are reused from chunked tensors.  Only schedule
features are rebuilt, so replacing a pilot lambda context with the context
fitted on the complete training split does not launch Flow again.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import random
from dataclasses import replace
from pathlib import Path
from typing import Iterable

import torch

from bridge.dataset import DatasetGenerator, DatasetManifest
from bridge.dataset_plan import build_plan
from contracts import canonical_bytes
from surrogate.cycle import EXTRA_CONFIG, PILOT_CONFIG
from surrogate.features import ScheduleFeatureizer, SurrogateInput
from surrogate.model import _features
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.ood import FeatureRange, TrainingDomain, fit_domain


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-chunks", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument(
        "--in-memory",
        action="store_true",
        help="не писать промежуточные corrected chunks (требует около 8 ГБ RAM)",
    )
    return parser


def _materials(model_dir: Path, data_root: Path):
    result = []
    for name, seed, config in (
        ("dataset-main", 20260816, PILOT_CONFIG),
        ("dataset-extra-500", 20260817, EXTRA_CONFIG),
    ):
        generator = DatasetGenerator(
            model_dir,
            data_root / name,
            max_workers=1,
            timeout_seconds=1.0,
            compact_artifacts=False,
            load_responses=False,
        )
        accepted, skipped = generator.prepare(
            build_plan(generator.base_schedule(), seed=seed, config=config)
        )
        if skipped:
            raise RuntimeError(f"{name}: статически отсеяно {len(skipped)} сценариев")
        result.extend((name, material) for material in accepted)
    return result


def _merge_domains(domains: Iterable[TrainingDomain]) -> TrainingDomain:
    items = tuple(domains)
    if not items:
        raise RuntimeError("обучающий split не дал OOD-domain")
    ranges: dict[str, tuple[float, float]] = {}
    categories: dict[str, frozenset[str]] = {}
    schedule_hashes: list[str] = []
    n_nodes = 0
    for domain in items:
        for interval in domain.ranges:
            low, high = ranges.get(interval.name, (interval.low, interval.high))
            ranges[interval.name] = (min(low, interval.low), max(high, interval.high))
        for name, values in domain.categories:
            categories[name] = categories.get(name, frozenset()) | values
        schedule_hashes.extend(domain.schedule_hashes)
        n_nodes += domain.n_nodes
    return TrainingDomain(
        ranges=tuple(
            FeatureRange(name, low, high)
            for name, (low, high) in sorted(ranges.items())
        ),
        categories=tuple(sorted(categories.items())),
        static_feature_names=items[0].static_feature_names,
        n_nodes=n_nodes,
        schedule_hashes=tuple(schedule_hashes),
    )


def _canonical_buckets(materials, seed: int) -> dict[tuple[str, str], str]:
    """Reproduce ``cycle._train_combined`` membership exactly.

    ``DatasetGenerator.build`` sorts each source report by scenario id before
    the pilot and extra reports are concatenated.  A response-derived feature
    context fitted by the production cycle is valid only for that same train
    membership; trusting bucket labels from an experimental tensor artifact
    can leak held-out responses through lambda.
    """

    canonical = sorted(
        range(len(materials)),
        key=lambda index: (
            0 if materials[index][0] == "dataset-main" else 1,
            materials[index][1].spec.scenario_id,
        ),
    )
    shuffled = list(range(len(canonical)))
    random.Random(seed).shuffle(shuffled)
    n_test = n_validation = max(1, round(len(canonical) * 0.15))
    test_positions = set(shuffled[:n_test])
    validation_positions = set(shuffled[n_test : n_test + n_validation])
    result = {}
    for position, material_index in enumerate(canonical):
        source, material = materials[material_index]
        bucket = (
            "test"
            if position in test_positions
            else "validation"
            if position in validation_positions
            else "train"
        )
        result[(source, material.spec.scenario_id)] = bucket
    return result


def _verify_context_membership(
    artifact: ModelZFeatureArtifact,
    buckets: dict[tuple[str, str], str],
    data_root: Path,
) -> None:
    """Prove that the response-derived context saw exactly this train split."""

    metadata = {}
    for source in ("dataset-main", "dataset-extra-500"):
        rows = DatasetManifest(data_root / source / "manifest.jsonl").read()
        for row in rows:
            if not row.response_hash:
                continue
            key = (source, row.scenario_id)
            previous = metadata.get(key)
            identity = (row.canonical_schedule_hash, row.response_hash)
            if previous is not None and previous != identity:
                raise RuntimeError(f"manifest identity изменилась для {key}")
            metadata[key] = identity
    train_keys = [key for key, bucket in buckets.items() if bucket == "train"]
    missing = set(train_keys) - set(metadata)
    if missing:
        raise RuntimeError(f"manifest не содержит response hash для {len(missing)} train")
    source_payload = {
        "dataset_hash": artifact.dataset_hash,
        "responses": sorted(metadata[key][1] for key in train_keys),
        "schedules": sorted(metadata[key][0] for key in train_keys),
    }
    actual = hashlib.sha256(canonical_bytes(source_payload)).hexdigest()
    if actual != artifact.lambda_source_hash:
        raise RuntimeError(
            "feature context fitted на другом train split: "
            f"{actual} != {artifact.lambda_source_hash}"
        )


def _model_input(
    featureizer: ScheduleFeatureizer,
    artifact: ModelZFeatureArtifact,
    schedule,
) -> SurrogateInput:
    return replace(
        featureizer.transform(schedule, artifact.context),
        lambda_edges=(),
    )


def main() -> int:
    args = _parser().parse_args()
    chunks = sorted(args.source_chunks.glob("chunk_*.pt"))
    if not chunks:
        raise RuntimeError(f"нет source chunks в {args.source_chunks}")
    materials = _materials(args.model_dir, args.data_root)
    if len(materials) != 700:
        raise RuntimeError(f"ожидалось 700 сценариев, получено {len(materials)}")
    buckets = _canonical_buckets(materials, args.seed)
    if tuple(buckets.values()).count("train") != 490:
        raise RuntimeError("canonical split не дал 490 обучающих сценариев")

    artifact = ModelZFeatureArtifact.load(args.feature_context)
    if artifact.n_training_scenarios < 400:
        raise RuntimeError(
            "feature context не production: "
            f"n_training_scenarios={artifact.n_training_scenarios}"
        )
    _verify_context_membership(artifact, buckets, args.data_root)
    print(f"lambda_source_hash подтверждён: {artifact.lambda_source_hash}", flush=True)
    corrected_dir = args.output.with_suffix(".chunks")
    if not args.in_memory:
        corrected_dir.mkdir(parents=True, exist_ok=True)
    featureizer = ScheduleFeatureizer()
    material_index = 0
    retained_rows = []

    print(
        f"контекст: {artifact.n_training_scenarios} train-сценариев; "
        f"source chunks: {len(chunks)}",
        flush=True,
    )
    for source_path in chunks:
        destination = corrected_dir / source_path.name
        source_rows = torch.load(source_path, weights_only=False)
        if not args.in_memory and destination.exists():
            material_index += len(source_rows)
            print(f"пропуск {destination.name}", flush=True)
            continue
        corrected = []
        for row in source_rows:
            source_name, material = materials[material_index]
            if row["scenario_id"] != material.spec.scenario_id:
                raise RuntimeError(
                    f"позиция {material_index}: {row['scenario_id']} != "
                    f"{material.spec.scenario_id}"
                )
            candidate = _model_input(featureizer, artifact, material.schedule)
            x, well_index = _features(
                candidate, candidate.wells, scenario_context="mean"
            )
            if x.shape[0] != row["y"].shape[0] or not torch.equal(
                well_index, row["w"]
            ):
                raise RuntimeError(
                    f"{source_name}:{material.spec.scenario_id}: оси targets разошлись"
                )
            corrected.append(
                {
                    "bucket": buckets[(source_name, material.spec.scenario_id)],
                    "x": x,
                    "w": well_index,
                    "y": row["y"],
                    "n": int(x.shape[0]),
                    "scenario_id": material.spec.scenario_id,
                    "source_dataset": source_name,
                    "canonical_schedule_hash": candidate.canonical_schedule_hash,
                    "domain": fit_domain([candidate])
                    if row["bucket"] == "train"
                    else None,
                    "wells": candidate.wells if material_index == 0 else None,
                    "static_names": candidate.static_feature_names
                    if material_index == 0
                    else None,
                }
            )
            material_index += 1
        if args.in_memory:
            retained_rows.extend(corrected)
            print(f"в памяти {destination.name}: {len(corrected)} сценариев", flush=True)
        else:
            temporary = destination.with_suffix(".pt.tmp")
            torch.save(corrected, temporary)
            temporary.replace(destination)
            print(f"готов {destination.name}: {len(corrected)} сценариев", flush=True)
        del source_rows, corrected
        gc.collect()

    if material_index != len(materials):
        raise RuntimeError(f"обработано {material_index} из {len(materials)} сценариев")

    parts = {bucket: [] for bucket in ("train", "validation", "test")}
    counts = {bucket: [] for bucket in parts}
    identities = {bucket: [] for bucket in parts}
    domains = []
    wells = static_names = None
    row_sources = (
        ((None, retained_rows),)
        if args.in_memory
        else tuple((path, None) for path in sorted(corrected_dir.glob("chunk_*.pt")))
    )
    for path, in_memory_rows in row_sources:
        rows = (
            in_memory_rows
            if in_memory_rows is not None
            else torch.load(path, weights_only=False)
        )
        for row in rows:
            bucket = row["bucket"]
            parts[bucket].append((row["x"], row["w"], row["y"]))
            counts[bucket].append(row["n"])
            identities[bucket].append(
                {
                    "source_dataset": row["source_dataset"],
                    "scenario_id": row["scenario_id"],
                    "canonical_schedule_hash": row["canonical_schedule_hash"],
                }
            )
            if row["domain"] is not None:
                domains.append(row["domain"])
            if row["wells"] is not None:
                wells, static_names = row["wells"], row["static_names"]
        del rows
        gc.collect()
    tensors = {
        bucket: tuple(
            torch.cat([part[index] for part in parts[bucket]])
            for index in range(3)
        )
        for bucket in parts
    }
    for bucket, values in tensors.items():
        print(f"{bucket}: {values[0].shape[0]:,} узлов", flush=True)
    payload = {
        "format": "aios.surrogate-tensors.v2",
        "feature_context": str(args.feature_context),
        "feature_context_training_scenarios": artifact.n_training_scenarios,
        "split_order": "dataset-source-then-scenario-id",
        "dataset_hash": artifact.dataset_hash,
        "lambda_source_hash": artifact.lambda_source_hash,
        "tensors": tensors,
        "counts": counts,
        "identities": identities,
        "wells": wells,
        "static_names": static_names,
        "domain": _merge_domains(domains),
    }
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(args.output)
    print(f"готово: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
