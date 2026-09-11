from __future__ import annotations

import hashlib
import statistics
from dataclasses import replace

from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.optimization.application.environment import predict_economics
from backend.contexts.surrogate.application.adapter import ResponseAdapter
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.domain.metrics import ranking_metrics
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_errors import (
    MetricsReportError,
)
from backend.shared.hashing import canonical_bytes, hash_schedule


def _regression(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if len(actual) < 2:
        raise MetricsReportError("regression metrics require at least two scenarios")
    mean = statistics.fmean(actual)
    ss_total = sum((value - mean) ** 2 for value in actual)
    ss_residual = sum((a - p) ** 2 for a, p in zip(actual, predicted, strict=True))
    errors = [abs(a - p) for a, p in zip(actual, predicted, strict=True)]
    relative = [
        abs(a - p) / abs(a) * 100.0
        for a, p in zip(actual, predicted, strict=True)
        if abs(a) > 0.0
    ]
    relative.sort()
    return {
        "n_scenarios": len(actual),
        "r2": 1.0 - ss_residual / ss_total if ss_total > 0.0 else float("nan"),
        "mae_rub": statistics.fmean(errors),
        "mae_mln_rub": statistics.fmean(errors) / 1e6,
        "npv_error_pct_median": statistics.median(relative) if relative else float("nan"),
        "npv_error_pct_p95": (
            relative[min(len(relative) - 1, int(0.95 * len(relative)))]
            if relative
            else float("nan")
        ),
        "npv_error_pct_max": max(relative) if relative else float("nan"),
    }


def _ranking(actual: list[float], predicted: list[float]) -> dict[str, object]:
    metrics = ranking_metrics(actual, predicted)
    order = sorted(range(len(predicted)), key=lambda i: predicted[i], reverse=True)
    true_best = max(range(len(actual)), key=lambda i: actual[i])
    return {
        "n_candidates": metrics.n_candidates,
        "spearman": metrics.spearman_rank_correlation,
        "precision_at_k": {str(k): v for k, v in metrics.precision_at_k.items()},
        "regret_at_k_mln_rub": {
            str(k): v / 1e6 for k, v in metrics.regret_at_k_rub.items()
        },
        "true_best_rank": order.index(true_best) + 1,
    }


def _predict_response(env, schedule) -> tuple[dict[str, float], ResponseArtifact]:
    model_input = replace(ScheduleFeatureizer().transform(schedule, env.feature_context.context), lambda_edges=())
    scored = env.model.predict(model_input)
    states, intervals = ResponseAdapter().adapt(scored.output, schedule, env.real_history, env.control_dates)
    response = ResponseArtifact(
        source_run_id=f"surrogate-metrics:{env.model.version[:12]}",
        response_hash=hashlib.sha256(canonical_bytes({"schedule": hash_schedule(schedule)})).hexdigest(),
        state_at_date=states, interval_response=intervals,
    )
    return predict_economics(env, model_input, response), response


def _score_schedule(env, schedule) -> dict[str, float]:
    components, _ = _predict_response(env, schedule)
    return components


def _component_metrics(rows):
    actual = [row["npv_opm_rub"] for row in rows]
    return {
        name: {"regression": _regression(actual, [row[name] for row in rows]),
               "ranking": _ranking(actual, [row[name] for row in rows])}
        for name in ("direct", "physical", "blended") if name in rows[0]
    }
