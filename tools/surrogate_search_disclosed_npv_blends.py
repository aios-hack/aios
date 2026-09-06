"""Search small convex NPV ensembles using disclosed grouped-OOF predictions."""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

if __package__:
    from tools.surrogate_audit_disclosed_npv_candidates import _load_population, _write
    from tools.surrogate_benchmark_npv_models import (
        _apply_calibration,
        _cv_predict,
        _factories,
        _linear_calibration,
        _metrics,
        _view,
    )
else:
    from surrogate_audit_disclosed_npv_candidates import _load_population, _write
    from surrogate_benchmark_npv_models import (
        _apply_calibration,
        _cv_predict,
        _factories,
        _linear_calibration,
        _metrics,
        _view,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--screen-report", type=Path, required=True)
    parser.add_argument(
        "--augmentation-features", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--augmentation-labels", type=Path, action="append", default=[]
    )
    parser.add_argument("--candidate-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _at5(metrics: dict[str, Any], field: str, default: float) -> float:
    mapping = metrics["ranking"][field]
    return float(mapping.get(5, mapping.get("5", default)))


def _shortlist(candidates: list[dict[str, Any]]) -> list[str]:
    best_rho = max(
        item["oof"]["ranking"]["spearman_rank_correlation"] for item in candidates
    )
    broad = [
        item
        for item in candidates
        if item["oof"]["ranking"]["spearman_rank_correlation"] >= best_rho - 0.04
    ]
    selected: list[str] = []

    def add(items: list[dict[str, Any]]) -> None:
        for item in items:
            candidate_id = item["candidate_id"]
            if candidate_id not in selected:
                selected.append(candidate_id)

    add(sorted(broad, key=lambda item: (item["oof"]["rank_of_true_best"], item["oof"]["mae_rub"]))[:8])
    add(sorted(broad, key=lambda item: item["oof"]["mae_rub"])[:8])
    add(
        sorted(
            candidates,
            key=lambda item: (
                _at5(item["oof"], "regret_at_k_rub", math.inf),
                item["oof"]["rank_of_true_best"],
            ),
        )[:4]
    )
    for required in ("block-joint-s0-a0.3", "block-additive-s6-a1"):
        if required not in selected:
            selected.append(required)
    return selected


def _key(item: dict[str, Any]) -> tuple:
    metrics = item["metrics"]
    rank = int(metrics["rank_of_true_best"])
    return (
        rank > 5,
        rank,
        _at5(metrics, "regret_at_k_rub", math.inf),
        -_at5(metrics, "precision_at_k", 0.0),
        metrics["mae_rub"],
        -metrics["ranking"]["spearman_rank_correlation"],
        item["components"],
        item["weights"],
    )


def main() -> int:
    args = _parser().parse_args()
    if len(args.augmentation_features) != len(args.augmentation_labels):
        raise ValueError("augmentation feature/label counts differ")
    matrix, target, groups, population = _load_population(args)
    audit = json.loads(args.candidate_audit.read_text(encoding="utf-8"))
    screen = json.loads(args.screen_report.read_text(encoding="utf-8"))
    if (
        audit.get("status") != "complete"
        or audit.get("population_hash") != population["population_hash"]
        or audit.get("n_rows") != len(target)
    ):
        raise RuntimeError("candidate audit does not match disclosed population")
    candidates = audit["candidates"]
    shortlist = _shortlist(candidates)
    factories = _factories(seed=int(screen["seed"]), trees=int(screen["trees"]))
    predictions: dict[str, np.ndarray] = {}
    component_metrics = {}
    for candidate_id in shortlist:
        repeated = []
        for repeat in range(int(audit["repeats"])):
            predicted, _ = _cv_predict(
                factories[candidate_id],
                _view(matrix, candidate_id),
                target,
                groups,
                folds=int(audit["folds"]),
                seed=int(audit["seed"]) + 104729 * repeat,
            )
            repeated.append(predicted)
        averaged = np.stack(repeated).mean(axis=0)
        calibration = _linear_calibration(target, averaged)
        calibrated = _apply_calibration(averaged, calibration)
        predictions[candidate_id] = calibrated
        component_metrics[candidate_id] = _metrics(target, calibrated)
        print(f"blend component {len(predictions)}/{len(shortlist)} {candidate_id}", flush=True)
    best_component_rho = max(
        metrics["ranking"]["spearman_rank_correlation"]
        for metrics in component_metrics.values()
    )
    rho_floor = best_component_rho - 0.02
    evaluated = []

    def add(components: tuple[str, ...], weights: tuple[float, ...]) -> None:
        predicted = sum(
            weight * predictions[candidate_id]
            for candidate_id, weight in zip(components, weights, strict=True)
        )
        metrics = _metrics(target, predicted)
        if metrics["ranking"]["spearman_rank_correlation"] < rho_floor:
            return
        evaluated.append(
            {
                "components": list(components),
                "weights": [float(weight) for weight in weights],
                "metrics": metrics,
            }
        )

    for candidate_id in shortlist:
        add((candidate_id,), (1.0,))
    pair_grid = np.linspace(0.05, 0.95, 19)
    for first, second in itertools.combinations(shortlist, 2):
        for weight in pair_grid:
            add((first, second), (float(weight), float(1.0 - weight)))
    triple_grid = np.arange(0.1, 1.0, 0.1)
    for components in itertools.combinations(shortlist, 3):
        for first_weight in triple_grid:
            for second_weight in triple_grid:
                third_weight = 1.0 - first_weight - second_weight
                if third_weight >= 0.099999:
                    add(
                        components,
                        (
                            float(first_weight),
                            float(second_weight),
                            float(third_weight),
                        ),
                    )
    ranked = sorted(evaluated, key=_key)
    report = {
        "format": "aios.surrogate-disclosed-npv-blend-screen.v1",
        **population,
        "candidate_audit": str(args.candidate_audit),
        "shortlist": shortlist,
        "component_metrics": component_metrics,
        "rho_floor": rho_floor,
        "evaluated_blends": len(evaluated),
        "winner": ranked[0],
        "top_blends": ranked[:100],
    }
    _write(args.output, report)
    winner = report["winner"]
    print(
        f"blend winner rank={winner['metrics']['rank_of_true_best']} "
        f"components={winner['components']} weights={winner['weights']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
