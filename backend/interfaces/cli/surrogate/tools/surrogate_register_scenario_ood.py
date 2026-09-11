"""Bind a validated density guard to an existing production manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from backend.contexts.surrogate.application.ensemble import TrajectoryEnsemble
from backend.contexts.surrogate.application.model import TrajectorySurrogate
from backend.contexts.robustness.domain.scenario_ood import ScenarioDensityDomain
from backend.shared.json_io import read_json


def register(manifest: Path, domain_path: Path) -> None:
    payload = read_json(manifest)
    if payload.get("format") != "aios.surrogate-production-pointer.v1":
        raise ValueError("unsupported production manifest")
    checkpoint = manifest.parent / payload["trajectory_checkpoint"]
    model = (TrajectoryEnsemble.load(checkpoint) if checkpoint.suffix == ".json"
             else TrajectorySurrogate.load(checkpoint))
    domain = ScenarioDensityDomain.load(domain_path)
    if domain.dataset_hash != model.dataset_hash:
        raise ValueError("scenario OOD dataset differs from production trajectory")
    context = manifest.parent / payload["feature_context"]
    payload["scenario_ood"] = {
        "path": os.path.relpath(domain_path.resolve(), manifest.parent.resolve()),
        "sha256": hashlib.sha256(domain_path.read_bytes()).hexdigest(),
        "feature_context_sha256": hashlib.sha256(context.read_bytes()).hexdigest(),
    }
    temporary = manifest.with_suffix(manifest.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--domain", type=Path, required=True)
    args = parser.parse_args()
    register(args.manifest, args.domain)


if __name__ == "__main__":
    main()
