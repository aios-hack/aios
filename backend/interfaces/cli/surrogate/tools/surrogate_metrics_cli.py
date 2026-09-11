from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch

from backend.contexts.optimization.application.environment import load_environment
from backend.contexts.optimization.application.search_use_case import (
    RESPONSE,
)
from backend.contexts.optimization.application.verification_run import (
    LAMBDA,
)
from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
from backend.interfaces.cli.runner import run as run_cli
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_console import (
    _print_bhp,
    _print_effect,
)
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_holdout import (
    DEFAULT_HOLDOUT,
    load_frozen_holdout,
)
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_errors import (
    MetricsReportError,
)
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_report import (
    _held_out,
    _manifold,
)
from backend.shared.json_io import read_json
from backend.shared.resources import model_z_dir, normatives_xlsx

NORMATIVES = normatives_xlsx()
FORMAT = "aios.surrogate-metrics.v2"
DEFAULT_LABELS = Path("data/model-night-20260826-v2/npv_labels.json")
DEFAULT_TENSORS = Path("data/lean700/tensors_context_490_canonical.pt")
DEFAULT_MANIFOLD = Path("data")
MANIFOLD_GLOB = "constrained-opm-*"


DESCRIPTION = (
    "Surrogate card metrics: absolute NPV error, error of predicting the NPV "
    "difference between neighbours in the ranking, and the bhp channel error distribution."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--tensors", type=Path, default=DEFAULT_TENSORS)
    parser.add_argument("--split", default="test", choices=("train", "validation", "test"))
    parser.add_argument("--manifold-root", type=Path, default=DEFAULT_MANIFOLD)
    parser.add_argument("--manifold-glob", default=MANIFOLD_GLOB)
    parser.add_argument("--holdout", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        raise MetricsReportError(
            f"{what} not found: {path}. The metrics cannot be reproduced without it; "
            "an empty table in place of a number is forbidden."
        )
    return path


def main() -> int:
    args = _parser().parse_args()
    torch.set_num_threads(2)
    _require(args.labels, "the NPV labels file")
    _require(args.tensors, "the tensor cache")
    labels = read_json(args.labels)
    if labels.get("format") != "aios.surrogate-npv-labels.v1":
        raise MetricsReportError(f"unsupported labels format: {args.labels}")

    holdout = load_frozen_holdout(args.holdout)
    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=model_z_dir(),
        normatives_path=NORMATIVES,
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
    )

    payload = {
        "format": FORMAT,
        "provenance": {
            "checkpoint": str(artifacts.checkpoint),
            "npv_head": str(artifacts.npv_head),
            "feature_context": str(artifacts.feature_context),
            "source": artifacts.source,
            "model_version": env.model.version,
            "economic_model_version": env.npv_head.version,
            "source_sha256": {name: _sha256(Path(name)) for name in (
                "backend/contexts/surrogate/domain/network.py",
                "backend/contexts/surrogate/application/adapter.py",
                "backend/contexts/simulation/infrastructure/response_loader.py",
                "backend/contexts/optimization/application/environment.py",
                "backend/interfaces/cli/surrogate/tools/surrogate_metrics_report.py")},
            "labels": str(args.labels),
            "labels_sha256": _sha256(args.labels),
            "labels_dataset_hash": labels.get("dataset_hash"),
            "tensors": str(args.tensors),
            "split": args.split,
            **holdout.as_provenance(),
        },
        "held_out": _held_out(args, env, labels, holdout),
        "optimizer_manifold": _manifold(args, env, holdout),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for name in ("held_out", "optimizer_manifold"):
        table = payload[name]
        regression, ranking = table["regression"], table["ranking"]
        print(f"\n- {name}: {table['population']} -")
        print(f"  scenarios            {regression['n_scenarios']}")
        print(f"  Spearman             {ranking['spearman']:+.4f}")
        print(f"  rank of the true 1st {ranking['true_best_rank']} of {ranking['n_candidates']}")
        print(f"  R2                   {regression['r2']:+.4f}")
        print(f"  MAE                  {regression['mae_mln_rub']:.1f} mln RUB")
        print(f"  NPV error, median    {regression['npv_error_pct_median']:.3f}%")
        print(f"  NPV error, P95       {regression['npv_error_pct_p95']:.3f}%")
        _print_effect(table["effect"])
        if name == "optimizer_manifold":
            _print_bhp(table["bhp_channel"])
    if holdout.populated:
        print(
            f"\nfrozen holdout: {len(holdout.hashes)} schedules "
            f"excluded ({holdout.path})"
        )
    else:
        print(f"\nfrozen holdout IS NOT POPULATED: {holdout.reason}")
    print(f"\nreport: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
