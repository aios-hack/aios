"""Export the measured Lambda embedded in a feature context for optimizer use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from surrogate.model_z_context import ModelZFeatureArtifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite Lambda artifact: {args.output}")
    artifact = ModelZFeatureArtifact.load(args.feature_context)
    windows = artifact.context.lambda_windows
    if len(windows) != 1:
        raise RuntimeError(f"expected exactly one measured Lambda, got {len(windows)}")
    influence = windows[0]
    payload = {
        "format": "aios.lambda-exported-from-feature-context.v1",
        "provenance": {
            "feature_context": str(args.feature_context),
            "feature_context_sha256": _sha256(args.feature_context),
            "dataset_hash": artifact.dataset_hash,
            "lambda_source_hash": artifact.lambda_source_hash,
            "n_training_scenarios": artifact.n_training_scenarios,
            "blind_response_read": False,
        },
        "window_start": influence.window_start.isoformat(),
        "window_end": influence.window_end.isoformat(),
        "lag_months": influence.lag_months,
        "amplitude": influence.amplitude,
        "rank": influence.rank,
        "condition_number": influence.condition_number,
        "stability": influence.stability,
        "producers": list(influence.producers),
        "injectors": list(influence.injectors),
        "matrix": [list(row) for row in influence.matrix],
        "achievability_ok": dict(influence.achievability_ok),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(f"exported Lambda: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
