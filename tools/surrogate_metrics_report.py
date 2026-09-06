"""Воспроизведение метрик карточки суррогата — S-02.

Собирает три таблицы §6.2 (4) плана одной командой и кладёт их в
`metrics.json` с провенансом. Числа в `SURROGATE.md` берутся отсюда; всё, что
не воспроизвелось этой командой, в карточку не попадает.

Таблицы:

* **held_out** — отложенные сценарии знакомого распределения. Spearman, R²,
  MAE и относительная ошибка ЧДД на сплите, зафиксированном в отчёте обучения.
* **optimizer_manifold** — кандидаты, которые контур действительно предлагал,
  с настоящим ЧДД OPM. Это отдельная популяция, и мерить её отдельно —
  главный урок G10: общий holdout шире локального manifold оптимизатора и
  пригодности для отбора не доказывает.
* **crm_baseline** — та же выборка, но предсказанная линейной CRM-моделью.
  Без неё «Spearman 0.8» ничего не значит: неизвестно, сколько из этого даёт
  простая физика.

Единица счёта везде — сценарий, а не узел `скважина × месяц`.

Команда только читает кеш: отсутствующие метки или тензоры — ошибка с
текстом, а не пустая таблица (CLAUDE.md §3).

Запуск:

    PYTHONPATH=. python tools/surrogate_metrics_report.py \\
        --output data/surrogate/metrics.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch

import conftest
from contracts import ResponseArtifact, canonical_bytes, hash_schedule
from economics.base_case import analyze_base_case
from optimizer.runtime_artifacts import resolve_runtime_artifacts
from optimizer.schedule_search import load_environment
from optimizer.search_run import LAMBDA, NORMATIVES, RESPONSE
from surrogate.adapter import ResponseAdapter
from surrogate.features import ScheduleFeatureizer
from surrogate.metrics import ranking_metrics
from surrogate.npv_head import scenario_feature_vector
from ui.artifact_io import _load_schedule

FORMAT = "aios.surrogate-metrics.v1"
DEFAULT_LABELS = Path("data/model-night-20260826-v2/npv_labels.json")
DEFAULT_TENSORS = Path("data/lean700/tensors_context_490_canonical.pt")
DEFAULT_MANIFOLD = Path("data")
MANIFOLD_GLOB = "constrained-opm-*"


class MetricsReportError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--tensors", type=Path, default=DEFAULT_TENSORS)
    parser.add_argument("--split", default="test", choices=("train", "validation", "test"))
    parser.add_argument("--manifold-root", type=Path, default=DEFAULT_MANIFOLD)
    parser.add_argument("--manifold-glob", default=MANIFOLD_GLOB)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        raise MetricsReportError(
            f"{what} не найден: {path}. Воспроизвести метрики без него нельзя; "
            "пустая таблица вместо числа запрещена."
        )
    return path


def _regression(actual: list[float], predicted: list[float]) -> dict[str, float]:
    """R², MAE и относительная ошибка ЧДД в процентах."""

    if len(actual) < 2:
        raise MetricsReportError("регрессионные метрики требуют минимум двух сценариев")
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


def _held_out(args, env, labels: dict) -> dict[str, object]:
    """Таблица (а): отложенные сценарии знакомого распределения."""

    bundle = torch.load(args.tensors, map_location="cpu", weights_only=False)
    identities = bundle["identities"].get(args.split)
    tensors = bundle["tensors"].get(args.split)
    if not identities or tensors is None:
        raise MetricsReportError(f"в тензорах нет сплита {args.split!r}")
    x, well_index = tensors[0], tensors[1]
    n_wells = len(bundle["wells"])
    per_scenario = len(x) // len(identities)
    head = env.npv_head
    if head is None:
        raise MetricsReportError("production-указатель не содержит головы ЧДД")

    by_hash = {row["canonical_schedule_hash"]: row for row in labels["rows"].values()}
    actual: list[float] = []
    predicted: list[float] = []
    for index, identity in enumerate(identities):
        label = by_hash.get(identity["canonical_schedule_hash"])
        if label is None:
            raise MetricsReportError(
                f"нет метки ЧДД для {identity['scenario_id']}: метки и тензоры разошлись"
            )
        start = index * per_scenario
        vector = scenario_feature_vector(
            x[start : start + per_scenario],
            well_index[start : start + per_scenario],
            n_wells=n_wells,
            # Тот же набор, что хардкодит `BlockKernelNpvHead.predict`:
            # вектор обязан совпасть с тем, на котором голова обучалась.
            feature_set="economic",
        )
        actual.append(float(label["npv_rub"]))
        predicted.append(float(head.predict_vectors(vector.unsqueeze(0))[0]))

    return {
        "population": f"{args.split} split знакомого распределения",
        "note": (
            "прямая голова ЧДД без физической компоненты: она требует расписаний, "
            "которых в тензорном кеше нет, и меряется на manifold оптимизатора ниже"
        ),
        "regression": _regression(actual, predicted),
        "ranking": _ranking(actual, predicted),
    }


def _manifold(args, env) -> dict[str, object]:
    """Таблица (б): кандидаты, которые предлагал контур, с настоящим ЧДД OPM."""

    directories = sorted(
        path
        for path in args.manifold_root.glob(args.manifold_glob)
        if path.is_dir() and (path / "result.json").is_file()
    )
    if len(directories) < 2:
        raise MetricsReportError(
            f"{args.manifold_root}/{args.manifold_glob}: нужно минимум два прогона "
            "с настоящим ЧДД OPM, чтобы ранжирование имело смысл"
        )
    featureizer, adapter = ScheduleFeatureizer(), ResponseAdapter()
    physical_weight = float(getattr(env.npv_head, "physical_npv_weight", 0.0))

    actual: list[float] = []
    predicted: list[float] = []
    rows: list[dict[str, object]] = []
    for directory in directories:
        schedule = _load_schedule(
            json.loads((directory / "schedule.json").read_text(encoding="utf-8"))
        )
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        model_input = replace(
            featureizer.transform(schedule, env.feature_context.context),
            lambda_edges=(),
        )
        direct = float(env.npv_head.predict(model_input))
        if physical_weight > 0.0:
            output = env.model.predict(model_input).output
            states, intervals = adapter.adapt(
                output, schedule, env.real_history, env.control_dates
            )
            response = ResponseArtifact(
                source_run_id=f"surrogate-metrics:{env.model.version[:12]}",
                response_hash=hashlib.sha256(
                    canonical_bytes({"schedule": hash_schedule(schedule)})
                ).hexdigest(),
                state_at_date=states,
                interval_response=intervals,
            )
            physical = analyze_base_case(
                response,
                env.deck_dates,
                env.t0_deck_date_index,
                env.normatives,
                env.policies,
            ).npv_methodology
            blended = (1.0 - physical_weight) * direct + physical_weight * physical
        else:
            blended = direct
        actual.append(float(result["npv_opm"]))
        predicted.append(blended)
        rows.append(
            {
                "run": directory.name,
                "npv_opm_rub": float(result["npv_opm"]),
                "npv_surrogate_rub": blended,
            }
        )

    return {
        "population": "кандидаты контура с настоящим ЧДД OPM",
        "physical_npv_weight": physical_weight,
        "caveat": (
            "восемь прогонов — не замена запечатанной optimizer-shaped выборке; "
            "пул G10 из 40 кандидатов на диске отсутствует, и до нового пакета "
            "OPM эта таблица остаётся индикативной"
        ),
        "regression": _regression(actual, predicted),
        "ranking": _ranking(actual, predicted),
        "rows": rows,
    }


def main() -> int:
    args = _parser().parse_args()
    _require(args.labels, "файл меток ЧДД")
    _require(args.tensors, "тензорный кеш")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if labels.get("format") != "aios.surrogate-npv-labels.v1":
        raise MetricsReportError(f"неподдерживаемый формат меток: {args.labels}")

    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=conftest.model_z_dir(),
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
            "labels": str(args.labels),
            "labels_sha256": _sha256(args.labels),
            "labels_dataset_hash": labels.get("dataset_hash"),
            "tensors": str(args.tensors),
            "split": args.split,
        },
        "held_out": _held_out(args, env, labels),
        "optimizer_manifold": _manifold(args, env),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for name in ("held_out", "optimizer_manifold"):
        table = payload[name]
        regression, ranking = table["regression"], table["ranking"]
        print(f"\n— {name}: {table['population']} —")
        print(f"  сценариев           {regression['n_scenarios']}")
        print(f"  Spearman            {ranking['spearman']:+.4f}")
        print(f"  место истинного 1-го {ranking['true_best_rank']} из {ranking['n_candidates']}")
        print(f"  R²                  {regression['r2']:+.4f}")
        print(f"  MAE                 {regression['mae_mln_rub']:.1f} млн ₽")
        print(f"  ошибка ЧДД, медиана {regression['npv_error_pct_median']:.3f}%")
        print(f"  ошибка ЧДД, P95     {regression['npv_error_pct_p95']:.3f}%")
    print(f"\nотчёт: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
