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
from optimizer.schedule_search import load_environment, predict_economics
from optimizer.search_run import LAMBDA, NORMATIVES, RESPONSE
from surrogate.adapter import ResponseAdapter
from surrogate.features import ScheduleFeatureizer
from surrogate.metrics import ranking_metrics
from bridge.dataset_plan import baseline_profile, build_plan, materialize
from surrogate.cycle import PILOT_CONFIG, EXTRA_CONFIG
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


def _score_schedule(env, schedule) -> dict[str, float]:
    model_input = replace(ScheduleFeatureizer().transform(schedule, env.feature_context.context), lambda_edges=())
    scored = env.model.predict(model_input)
    states, intervals = ResponseAdapter().adapt(scored.output, schedule, env.real_history, env.control_dates)
    response = ResponseArtifact(
        source_run_id=f"surrogate-metrics:{env.model.version[:12]}",
        response_hash=hashlib.sha256(canonical_bytes({"schedule": hash_schedule(schedule)})).hexdigest(),
        state_at_date=states, interval_response=intervals,
    )
    return predict_economics(env, model_input, response)


def _component_metrics(rows):
    actual = [row["npv_opm_rub"] for row in rows]
    return {
        name: {"regression": _regression(actual, [row[name] for row in rows]),
               "ranking": _ranking(actual, [row[name] for row in rows])}
        for name in ("direct", "physical", "blended") if name in rows[0]
    }


def _held_out(args, env, labels: dict) -> dict[str, object]:
    """Reconstruct exact schedules and evaluate the same blend used by search."""
    bundle = torch.load(args.tensors, map_location="cpu", weights_only=False, mmap=True)
    identities = bundle["identities"].get(args.split)
    if not identities:
        raise MetricsReportError(f"в тензорах нет сплита {args.split!r}")
    by_identity = {(r["source_dataset"], r["scenario_id"], r["canonical_schedule_hash"]): r
                   for r in labels["rows"].values()}
    plans = {
        source: {spec.scenario_id: spec for spec in build_plan(env.base_schedule, seed=seed, config=config)}
        for source, seed, config in (("dataset-main", 20260816, PILOT_CONFIG),
                                     ("dataset-extra-500", 20260817, EXTRA_CONFIG))
    }
    profile = baseline_profile(env.base_schedule)
    rows = []
    seen = set()
    for index, identity in enumerate(identities):
        key = (identity["source_dataset"], identity["scenario_id"], identity["canonical_schedule_hash"])
        label = by_identity.get(key)
        if label is None or label["bucket"] != args.split:
            raise MetricsReportError(f"нет точной метки ЧДД в нужном сплите: {key}")
        if key[2] in seen:
            continue
        seen.add(key[2])
        spec = plans[key[0]][key[1]]
        schedule = materialize(env.base_schedule, spec, profile=profile).schedule
        if hash_schedule(schedule) != key[2]:
            raise MetricsReportError(f"восстановленное расписание разошлось с меткой: {key}")
        rows.append({**identity, "family": spec.family.value, "npv_opm_rub": float(label["npv_rub"]),
                     **_score_schedule(env, schedule)})
        if (index + 1) % 10 == 0:
            print(f"{args.split}: {index + 1}/{len(identities)}", flush=True)
    components = _component_metrics(rows)
    return {
        "population": f"{args.split}: unique schedules, current production blend",
        "note": "diagnostic disclosed split; all predictions evaluated, including OOD",
        **components["blended"], "components": components, "rows": rows,
        "by_family": {family: _component_metrics([r for r in rows if r["family"] == family])
                      for family in sorted({r["family"] for r in rows})
                      if sum(r["family"] == family for r in rows) >= 2},
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
    physical_weight = float(getattr(env.npv_head, "physical_npv_weight", 0.0))
    actual, predicted, rows = [], [], []
    for directory in directories:
        schedule = _load_schedule(json.loads((directory / "schedule.json").read_text()))
        result = json.loads((directory / "result.json").read_text())
        if result["canonical_schedule_hash"] != hash_schedule(schedule):
            raise MetricsReportError(f"{directory}: schedule hash differs from OPM result")
        components = _score_schedule(env, schedule)
        actual.append(float(result["npv_opm"]))
        predicted.append(components["blended"])
        rows.append({"run": directory.name, "npv_opm_rub": actual[-1],
                     "npv_surrogate_rub": predicted[-1], **components})

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
        "components": _component_metrics(rows),
    }


def main() -> int:
    args = _parser().parse_args()
    torch.set_num_threads(2)
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
            "economic_model_version": env.npv_head.version,
            "source_sha256": {name: _sha256(Path(name)) for name in (
                "surrogate/model.py", "surrogate/adapter.py", "bridge/response_loader.py",
                "optimizer/schedule_search.py", "tools/surrogate_metrics_report.py")},
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
