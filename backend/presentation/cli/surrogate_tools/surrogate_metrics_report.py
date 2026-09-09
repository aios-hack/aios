
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch
from backend.ml.surrogate.model import _legacy_checkpoint_modules

from backend.infrastructure.resources import model_z_dir, normatives_xlsx
from backend.core.contracts import (
    ResponseArtifact,
    StateAtDate,
    canonical_bytes,
    hash_schedule,
)
from backend.domain.economics.base_case import analyze_base_case, load_response_artifact
from backend.application.optimization.runtime_artifacts import resolve_runtime_artifacts
from backend.application.optimization.schedule_search import load_environment, predict_economics
from backend.application.optimization.search_run import LAMBDA, RESPONSE
from backend.ml.surrogate.adapter import ResponseAdapter
from backend.ml.surrogate.features import ScheduleFeatureizer
from backend.ml.surrogate.metrics import ranking_metrics
from backend.infrastructure.opm.dataset_plan import baseline_profile, build_plan, materialize
from backend.ml.surrogate.cycle import PILOT_CONFIG, EXTRA_CONFIG
from backend.presentation.ui_export.artifact_io import _load_schedule

NORMATIVES = normatives_xlsx()
FORMAT = "aios.surrogate-metrics.v2"
DEFAULT_LABELS = Path("data/model-night-20260826-v2/npv_labels.json")
DEFAULT_TENSORS = Path("data/lean700/tensors_context_490_canonical.pt")
DEFAULT_MANIFOLD = Path("data")
MANIFOLD_GLOB = "constrained-opm-*"
EFFECT_THRESHOLD_RUB = 1_000_000.0
DESCRIPTION = (
    "Метрики карточки суррогата: абсолютная ошибка ЧДД, ошибка предсказания "
    "разницы ЧДД между соседями по ранжированию и распределение ошибки канала bhp."
)


class MetricsReportError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
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


def _quantile(ordered: list[float], share: float) -> float:
    if not ordered:
        raise MetricsReportError(
            "квантиль пустой выборки не определён; ноль вместо числа запрещён"
        )
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def _distribution(values: list[float], what: str) -> dict[str, float]:
    if not values:
        raise MetricsReportError(
            f"{what}: выборка пуста, распределение не считается; "
            "ноль вместо числа запрещён"
        )
    ordered = sorted(values)
    return {
        "n": float(len(ordered)),
        "median": statistics.median(ordered),
        "p95": _quantile(ordered, 0.95),
        "max": ordered[-1],
    }


def _scaled_distribution(values: list[float], what: str, scale: float) -> dict[str, float]:
    distribution = _distribution(values, what)
    scaled = {name: value / scale for name, value in distribution.items() if name != "n"}
    scaled["n"] = float(len(values))
    return scaled


def _adjacent_pairs(actual: list[float]) -> list[tuple[int, int]]:
    if len(actual) < 2:
        raise MetricsReportError(
            "ошибка эффекта требует минимум двух сценариев: разницы между "
            "одним сценарием не существует"
        )
    order = sorted(range(len(actual)), key=lambda i: actual[i], reverse=True)
    return list(zip(order, order[1:]))


def _effect_error(
    actual: list[float],
    predicted: list[float],
    *,
    threshold_rub: float = EFFECT_THRESHOLD_RUB,
) -> dict[str, object]:
    if len(actual) != len(predicted):
        raise MetricsReportError(
            f"сценариев {len(actual)} по факту и {len(predicted)} по прогнозу"
        )
    if threshold_rub <= 0.0:
        raise MetricsReportError(
            "порог значимости разницы ЧДД должен быть положительным"
        )
    pairs = _adjacent_pairs(actual)
    relative: list[float] = []
    absolute: list[float] = []
    degenerate: list[float] = []
    rows: list[dict[str, object]] = []
    for position, (high, low) in enumerate(pairs, start=1):
        true_delta = actual[high] - actual[low]
        predicted_delta = predicted[high] - predicted[low]
        error = abs(predicted_delta - true_delta)
        absolute.append(error)
        significant = abs(true_delta) >= threshold_rub
        share = error / abs(true_delta) * 100.0 if significant else None
        if significant:
            relative.append(share)
        else:
            degenerate.append(error)
        rows.append(
            {
                "pair_rank": position,
                "index_high": high,
                "index_low": low,
                "true_delta_rub": true_delta,
                "predicted_delta_rub": predicted_delta,
                "absolute_error_rub": error,
                "relative_error_pct": share,
                "significant": significant,
                "sign_agrees": (predicted_delta > 0.0) == (true_delta > 0.0),
            }
        )
    payload: dict[str, object] = {
        "pairing": "adjacent pairs in the true-NPV ranking",
        "pairing_rationale": (
            "оптимизатор выбирает между соседями по ранжированию, поэтому "
            "мерится ошибка ровно той разницы, по которой принимается решение; "
            "все пары выборки завышают качество за счёт далёких пар, а близость "
            "по расписанию из артефакта не восстанавливается"
        ),
        "n_pairs": len(pairs),
        "significance_threshold_rub": threshold_rub,
        "n_significant_pairs": len(relative),
        "n_degenerate_pairs": len(degenerate),
        "degenerate_policy": (
            "пара с |истинной разницей| ниже порога в относительную ошибку не "
            "входит и считается отдельно по абсолютной: деление на почти ноль "
            "меряет не модель, а деление"
        ),
        "absolute_error_mln_rub": _scaled_distribution(
            absolute, "абсолютная ошибка эффекта", 1e6
        ),
        "sign_agreement": sum(1 for row in rows if row["sign_agrees"]) / len(rows),
        "rows": rows,
    }
    if relative:
        distribution = _distribution(relative, "относительная ошибка эффекта")
        payload["effect_error_pct_median"] = distribution["median"]
        payload["effect_error_pct_p95"] = distribution["p95"]
        payload["effect_error_pct_max"] = distribution["max"]
    else:
        payload["effect_error_pct_median"] = None
        payload["effect_error_pct_p95"] = None
        payload["effect_error_pct_max"] = None
        payload["relative_error_unavailable"] = (
            f"ни одна из {len(pairs)} пар не имеет истинной разницы ЧДД выше "
            f"{threshold_rub:.0f} ₽: относительная ошибка эффекта на этой "
            "выборке не определена, читать абсолютную"
        )
    if degenerate:
        payload["degenerate_absolute_error_mln_rub"] = _scaled_distribution(
            degenerate, "абсолютная ошибка вырожденных пар", 1e6
        )
    return payload


def _bhp_absolute_errors(
    predicted_states: Sequence[StateAtDate], actual_states: Sequence[StateAtDate]
) -> list[float]:
    by_key = {(state.well, state.deck_date_index): state for state in actual_states}
    if len(by_key) != len(actual_states):
        raise MetricsReportError(
            "в фактических состояниях пара (скважина, дата дека) встречается дважды"
        )
    errors: list[float] = []
    for state in predicted_states:
        fact = by_key.get((state.well, state.deck_date_index))
        if fact is None:
            raise MetricsReportError(
                f"нет фактического состояния для {state.well} на шаге дека "
                f"{state.deck_date_index}: канал bhp сравнить не с чем"
            )
        errors.append(abs(state.bhp - fact.bhp))
    if not errors:
        raise MetricsReportError(
            "канал bhp: ни одного предсказанного состояния, распределение не считается"
        )
    return errors


def _bhp_channel(per_scenario: list[tuple[str, list[float]]]) -> dict[str, object]:
    if not per_scenario:
        raise MetricsReportError(
            "канал bhp: ни одного сценария с откликом OPM; δ для SRCH-14 без "
            "факта не выводится"
        )
    pooled: list[float] = []
    for _, errors in per_scenario:
        pooled.extend(errors)
    distribution = _distribution(pooled, "ошибка канала bhp")
    return {
        "channel": "bhp",
        "unit": "bar",
        "source": "StateAtDate.bhp: прогноз суррогата против отклика OPM",
        "consumer": "SRCH-14: δ для согласования гейтов по BHP между поиском и сдачей",
        "n_states": int(distribution["n"]),
        "n_scenarios": len(per_scenario),
        "bhp_error_bar_median": distribution["median"],
        "bhp_error_bar_p95": distribution["p95"],
        "bhp_error_bar_max": distribution["max"],
        "per_scenario": [
            {
                "run": name,
                "n_states": int(_distribution(errors, "ошибка канала bhp")["n"]),
                "bhp_error_bar_median": _distribution(errors, "ошибка канала bhp")["median"],
                "bhp_error_bar_p95": _distribution(errors, "ошибка канала bhp")["p95"],
            }
            for name, errors in per_scenario
        ],
    }


def _component_metrics(rows):
    actual = [row["npv_opm_rub"] for row in rows]
    return {
        name: {"regression": _regression(actual, [row[name] for row in rows]),
               "ranking": _ranking(actual, [row[name] for row in rows])}
        for name in ("direct", "physical", "blended") if name in rows[0]
    }


def _held_out(args, env, labels: dict) -> dict[str, object]:
    with _legacy_checkpoint_modules():
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
        schedule = materialize(env.base_schedule, spec).schedule
        if hash_schedule(schedule) != key[2]:
            raise MetricsReportError(f"восстановленное расписание разошлось с меткой: {key}")
        rows.append({**identity, "family": spec.family.value, "npv_opm_rub": float(label["npv_rub"]),
                     **_score_schedule(env, schedule)})
        if (index + 1) % 10 == 0:
            print(f"{args.split}: {index + 1}/{len(identities)}", flush=True)
    components = _component_metrics(rows)
    actual = [row["npv_opm_rub"] for row in rows]
    return {
        "population": f"{args.split}: unique schedules, current production blend",
        "note": "diagnostic disclosed split; all predictions evaluated, including OOD",
        **components["blended"],
        "effect": _effect_error(actual, [row["blended"] for row in rows]),
        "bhp_channel_unavailable": (
            "метки сплита содержат только ЧДД OPM, отклика StateAtDate в них нет: "
            "ошибка канала bhp считается там, где на диске лежит response.json OPM"
        ),
        "components": components, "rows": rows,
        "by_family": {family: _component_metrics([r for r in rows if r["family"] == family])
                      for family in sorted({r["family"] for r in rows})
                      if sum(r["family"] == family for r in rows) >= 2},
    }


def _manifold(args, env) -> dict[str, object]:
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
    bhp_per_scenario: list[tuple[str, list[float]]] = []
    missing_response: list[str] = []
    for directory in directories:
        schedule = _load_schedule(json.loads((directory / "schedule.json").read_text()))
        result = json.loads((directory / "result.json").read_text())
        if result["canonical_schedule_hash"] != hash_schedule(schedule):
            raise MetricsReportError(f"{directory}: schedule hash differs from OPM result")
        components, response = _predict_response(env, schedule)
        actual.append(float(result["npv_opm"]))
        predicted.append(components["blended"])
        rows.append({"run": directory.name, "npv_opm_rub": actual[-1],
                     "npv_surrogate_rub": predicted[-1], **components})
        opm_response = directory / "response.json"
        if opm_response.is_file():
            bhp_per_scenario.append((
                directory.name,
                _bhp_absolute_errors(
                    response.state_at_date,
                    load_response_artifact(opm_response).state_at_date,
                ),
            ))
        else:
            missing_response.append(directory.name)

    bhp: dict[str, object]
    if bhp_per_scenario:
        bhp = _bhp_channel(bhp_per_scenario)
        if missing_response:
            bhp["scenarios_without_opm_response"] = missing_response
    else:
        bhp = {
            "channel": "bhp",
            "unit": "bar",
            "unavailable": (
                "ни в одном прогоне нет response.json с откликом OPM: ошибку "
                "канала bhp не с чем сравнивать, число не выводится"
            ),
            "scenarios_without_opm_response": missing_response,
        }

    return {
        "effect": _effect_error(actual, predicted),
        "bhp_channel": bhp,
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


def _print_effect(effect: dict[str, object]) -> None:
    print(f"  пар соседей по рангу {effect['n_pairs']}"
          f" (значимых {effect['n_significant_pairs']},"
          f" вырожденных {effect['n_degenerate_pairs']})")
    median, p95 = effect["effect_error_pct_median"], effect["effect_error_pct_p95"]
    if median is None or p95 is None:
        print(f"  ошибка эффекта      {effect['relative_error_unavailable']}")
    else:
        print(f"  ошибка эффекта, медиана {median:.3f}%")
        print(f"  ошибка эффекта, P95     {p95:.3f}%")
    absolute = effect["absolute_error_mln_rub"]
    print(f"  ошибка эффекта, абс. медиана {absolute['median']:.3f} млн ₽,"
          f" P95 {absolute['p95']:.3f} млн ₽")


def _print_bhp(bhp: dict[str, object]) -> None:
    if "unavailable" in bhp:
        print(f"  канал bhp           {bhp['unavailable']}")
        return
    print(f"  ошибка bhp, медиана {bhp['bhp_error_bar_median']:.3f} бар"
          f" по {bhp['n_states']} состояниям")
    print(f"  ошибка bhp, P95     {bhp['bhp_error_bar_p95']:.3f} бар")


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
                "backend/ml/surrogate/model.py", "backend/ml/surrogate/adapter.py", "backend/infrastructure/opm/response_loader.py",
                "backend/application/optimization/schedule_search.py", "backend/presentation/cli/surrogate_tools/surrogate_metrics_report.py")},
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
        _print_effect(table["effect"])
        if name == "optimizer_manifold":
            _print_bhp(table["bhp_channel"])
    print(f"\nотчёт: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
