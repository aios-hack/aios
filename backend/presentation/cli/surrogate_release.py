"""Package the validated production weights and guards without retraining or promotion."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from backend.application.optimization.runtime_artifacts import resolve_runtime_artifacts, validate_runtime_economic_head
from backend.application.optimization.schedule_search import _validate_npv_head_compatibility
from backend.ml.surrogate.ensemble import TrajectoryEnsemble
from backend.ml.surrogate.model import TrajectorySurrogate
from backend.ml.surrogate.npv_block_head import load_direct_npv_head
from backend.ml.surrogate.scenario_ood import ScenarioDensityDomain


def package(manifest: Path, destination: Path) -> Path:
    if destination.exists():
        raise FileExistsError(f"release already exists: {destination}")
    manifest = manifest.resolve()
    root = manifest.parent
    artifacts = resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(manifest)})
    model = (TrajectoryEnsemble.load(artifacts.checkpoint) if artifacts.checkpoint.suffix == ".json"
             else TrajectorySurrogate.load(artifacts.checkpoint))
    head = load_direct_npv_head(artifacts.npv_head)
    validate_runtime_economic_head(artifacts, head)
    _validate_npv_head_compatibility(head, model, artifacts.feature_context)
    domain = ScenarioDensityDomain.load(artifacts.scenario_ood)
    if domain.dataset_hash != model.dataset_hash:
        raise ValueError("scenario OOD belongs to a different dataset")
    paths = [manifest, artifacts.checkpoint, artifacts.feature_context, artifacts.npv_head, artifacts.scenario_ood]
    if isinstance(model, TrajectoryEnsemble):
        paths.extend(model.member_paths)
    relative = {path.resolve().relative_to(root): path.resolve() for path in paths}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".surrogate-release-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for target, source in relative.items():
            output = staging / target
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
        metadata = {
            "format": "aios.surrogate-release.v1", "weights_changed": False,
            "trajectory_version": model.version, "economic_version": head.version,
            "scenario_ood_version": domain.version,
            "manifest": str(manifest.relative_to(root)),
            "files_sha256": {str(path): hashlib.sha256((staging / path).read_bytes()).hexdigest()
                             for path in sorted(relative)},
        }
        (staging / "release.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(staging / manifest.name)})
        staging.rename(destination)
    return destination / manifest.name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package(args.manifest, args.output))


if __name__ == "__main__":
    main()
