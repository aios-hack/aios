"""Build a response-free train+validation NPV feature cache from schedules."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import replace
from pathlib import Path

import torch

from bridge.dataset import DatasetGenerator
from bridge.dataset_plan import build_plan, materialize
from contracts import hash_schedule
from surrogate.cycle import EXTRA_CONFIG, PILOT_CONFIG
from surrogate.features import ScheduleFeatureizer
from surrogate.model import _features
from surrogate.model_z_context import ModelZFeatureArtifact
from surrogate.npv_head import feature_implementation_hash, scenario_feature_vector

SOURCES = (
    ("dataset-main", 20260816, PILOT_CONFIG),
    ("dataset-extra-500", 20260817, EXTRA_CONFIG),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--selection-identities", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_identities(path: Path) -> tuple[list[dict], str]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    identities = payload.get("identities")
    if (
        payload.get("format") != "aios.npv-selection-features.v1"
        or not isinstance(identities, list)
        or len(identities) != 595
        or any(item.get("bucket") not in {"train", "validation"} for item in identities)
    ):
        raise RuntimeError("selection identity source is not the locked 595 population")
    if len(
        {(item["source_dataset"], item["scenario_id"]) for item in identities}
    ) != len(identities):
        raise RuntimeError("selection identity source contains duplicate rows")
    dataset_hash = payload.get("dataset_hash")
    if not isinstance(dataset_hash, str) or len(dataset_hash) != 64:
        raise RuntimeError("selection identity source lacks dataset hash")
    return identities, dataset_hash


def _specs(
    model_dir: Path, data_root: Path
) -> dict[tuple[str, str], tuple[object, object]]:
    result = {}
    for source, seed, config in SOURCES:
        generator = DatasetGenerator(
            model_dir,
            data_root / source,
            max_workers=1,
            timeout_seconds=1.0,
            compact_artifacts=False,
            load_responses=False,
        )
        base = generator.base_schedule()
        plan = build_plan(base, seed=seed, config=config)
        for spec in plan.specs:
            key = (source, spec.scenario_id)
            if key in result:
                raise RuntimeError(f"duplicate plan scenario: {key}")
            result[key] = (base, spec)
    return result


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite selection cache: {args.output}")
    input_sha256 = {
        "feature_context": _sha256(args.feature_context),
        "selection_identities": _sha256(args.selection_identities),
        "feature_implementation": feature_implementation_hash(),
    }
    identities, dataset_hash = _load_identities(args.selection_identities)
    context = ModelZFeatureArtifact.load(args.feature_context)
    if context.dataset_hash != dataset_hash:
        raise RuntimeError("feature context/selection dataset hashes differ")
    specs = _specs(args.model_dir, args.data_root)
    featureizer = ScheduleFeatureizer()
    vectors = []
    wells: tuple[str, ...] | None = None
    static_names: tuple[str, ...] | None = None
    for index, identity in enumerate(identities, start=1):
        key = (identity["source_dataset"], identity["scenario_id"])
        if key not in specs:
            raise RuntimeError(f"selection identity is absent from plans: {key}")
        base, spec = specs[key]
        material = materialize(base, spec)
        schedule_hash = hash_schedule(material.schedule)
        if schedule_hash != identity["canonical_schedule_hash"]:
            raise RuntimeError(f"{key}: canonical schedule hash differs")
        candidate = replace(
            featureizer.transform(material.schedule, context.context),
            lambda_edges=(),
        )
        wells = wells or candidate.wells
        static_names = static_names or candidate.static_feature_names
        if candidate.wells != wells or candidate.static_feature_names != static_names:
            raise RuntimeError(f"{key}: feature axes differ")
        x, well_index = _features(candidate, wells, scenario_context=False)
        vectors.append(
            scenario_feature_vector(
                x,
                well_index,
                n_wells=len(wells),
                feature_set="economic",
            ).to(torch.float32)
        )
        if index == 1 or index % 25 == 0 or index == len(identities):
            print(f"selection feature cache {index}/{len(identities)}", flush=True)
    matrix = torch.stack(vectors)
    if matrix.shape != (595, 4406) or not bool(torch.isfinite(matrix).all()):
        raise RuntimeError("selection feature matrix is incomplete or non-finite")
    final_sha256 = {
        "feature_context": _sha256(args.feature_context),
        "selection_identities": _sha256(args.selection_identities),
        "feature_implementation": feature_implementation_hash(),
    }
    if final_sha256 != input_sha256:
        raise RuntimeError("selection feature inputs changed during cache build")
    payload = {
        "format": "aios.npv-selection-features.v2",
        "response_data_read": False,
        "historical_test_read": False,
        "dataset_hash": dataset_hash,
        "feature_set": "economic",
        "feature_width": matrix.shape[1],
        "feature_provenance_hash": input_sha256["feature_implementation"],
        "feature_context": str(args.feature_context),
        "feature_context_sha256": input_sha256["feature_context"],
        "identity_source": str(args.selection_identities),
        "identity_source_sha256": input_sha256["selection_identities"],
        "wells": wells,
        "static_names": static_names,
        "identities": identities,
        "features": matrix,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(args.output)
    print(f"selection feature cache written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
