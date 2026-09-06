"""Насколько ядровая голова ЧДД лучше простой модели на тех же признаках.

Заявлять «Spearman 0.83» бессмысленно, пока неизвестно, сколько даёт линейная
регрессия на том же входе. Приёмочный гейт §5.5 контракта и пункт 8 приёмки из
`DISCUSSIONS.md` требуют именно этого: сложная часть архитектуры считается
нужной, только если её удаление заметно ухудшает ранжирование.

Сравниваются три модели на одном сплите и одних признаках:

* **ridge** — гребневая регрессия на сценарном векторе (4406 признаков,
  тот же, что ест `BlockKernelNpvHead`). Обучается на train, гиперпараметр
  выбирается по validation, меряется на test;
* **single_feature** — одна координата сценарного вектора, выбранная по
  корреляции на train. Физический минимум: «чем больше суммарно отбираем,
  тем больше ЧДД»;
* **pairwise** — линейный ранжировщик с попарным логистическим лоссом на тех
  же признаках. Это центральная гипотеза `DISCUSSIONS.md`: учить порядок, а не
  абсолютный ЧДД;
* **gbdt** — scenario-level градиентный бустинг. Назван в приёмочных гейтах
  прямо: модель обязана его бить, иначе нелинейная голова не оправдана;
* **production** — сама голова из production-указателя.

Дополнительно считается абляция по блокам признакового вектора и парные
бутстрап-интервалы разниц: разница в третьем знаке на 105 сценариях ничего не
значит, и без интервала её нельзя предъявлять.

Никакой синтетики: метки ЧДД настоящие, из прогонов OPM.

Запуск:

    PYTHONPATH=. python tools/surrogate_baseline_comparison.py \\
        --output data/surrogate/baselines.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch

import conftest
from optimizer.runtime_artifacts import resolve_runtime_artifacts
from optimizer.schedule_search import load_environment
from optimizer.search_run import LAMBDA, NORMATIVES, RESPONSE
from surrogate.metrics import ranking_metrics
from surrogate.npv_head import scenario_feature_vector
from surrogate.npv_interval import ConformalNpvInterval

FORMAT = "aios.surrogate-baseline-comparison.v1"
DEFAULT_LABELS = Path("data/model-night-20260826-v2/npv_labels.json")
DEFAULT_TENSORS = Path("data/lean700/tensors_context_490_canonical.pt")
# Сетка гребня. Широкая и логарифмическая: подбирается по validation, поэтому
# конкретное значение — результат замера, а не константа с потолка.
RIDGE_GRID: tuple[float, ...] = (1e-2, 1e-1, 1.0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6)
PAIRWISE_L2_GRID: tuple[float, ...] = (1e-5, 1e-4, 1e-3, 1e-2, 1e-1)
PAIRWISE_EPOCHS = 400
PAIRWISE_LR = 0.05
GBDT_GRID: tuple[tuple[int, float, int], ...] = tuple(
    (leaves, rate, iterations)
    for leaves in (7, 15, 31)
    for rate in (0.03, 0.06, 0.1)
    for iterations in (200, 400)
)
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260905
# Границы блоков сценарного вектора — та же раскладка, что у
# `BlockKernelNpvHead.blocks`.
FEATURE_BLOCKS: tuple[tuple[str, int, int], ...] = (
    ("global", 0, 84),
    ("temporal", 84, 1260),
    ("well", 1260, 2908),
    ("economic", 2908, 4406),
)


class BaselineError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--tensors", type=Path, default=DEFAULT_TENSORS)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _vectors(bundle: dict, split: str) -> tuple[torch.Tensor, list[dict]]:
    identities = bundle["identities"].get(split)
    tensors = bundle["tensors"].get(split)
    if not identities or tensors is None:
        raise BaselineError(f"в тензорах нет сплита {split!r}")
    x, well_index = tensors[0], tensors[1]
    n_wells = len(bundle["wells"])
    per_scenario = len(x) // len(identities)
    rows = []
    for index in range(len(identities)):
        start = index * per_scenario
        rows.append(
            scenario_feature_vector(
                x[start : start + per_scenario],
                well_index[start : start + per_scenario],
                n_wells=n_wells,
                feature_set="economic",
            )
        )
    return torch.stack(rows), identities


def _labels_for(identities: list[dict], labels: dict) -> torch.Tensor:
    by_hash = {row["canonical_schedule_hash"]: row for row in labels["rows"].values()}
    values = []
    for identity in identities:
        row = by_hash.get(identity["canonical_schedule_hash"])
        if row is None:
            raise BaselineError(
                f"нет метки ЧДД для {identity['scenario_id']}: метки и тензоры разошлись"
            )
        values.append(float(row["npv_rub"]))
    return torch.tensor(values, dtype=torch.float64)


def _standardize(train: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    mean = train.mean(dim=0)
    scale = train.std(dim=0, unbiased=False)
    active = scale > 1e-9
    return mean, torch.where(active, scale, torch.ones_like(scale)), active


def _fit_ridge(
    features: torch.Tensor, targets: torch.Tensor, alpha: float
) -> tuple[torch.Tensor, float]:
    """Замкнутое решение гребня со свободным членом вне штрафа."""

    centered_y = targets - targets.mean()
    gram = features.T @ features + alpha * torch.eye(
        features.shape[1], dtype=features.dtype
    )
    weights = torch.linalg.solve(gram, features.T @ centered_y)
    return weights, float(targets.mean())


def _fit_pairwise(
    features: torch.Tensor, targets: torch.Tensor, l2: float
) -> torch.Tensor:
    """Линейный ранжировщик: softplus от разности оценок со знаком порядка.

    Пары строятся из train и не являются новыми независимыми наблюдениями —
    это дополнительные условия на те же 490 сценариев. Сплит и отбор
    гиперпараметра остаются на уровне сценария.
    """

    # Редукции float32 по нескольким потокам складывают слагаемые в разном
    # порядке, и оценка попарного ранжировщика гуляла между прогонами
    # (+0.8229 против +0.8456 на test, отбор l2 перескакивал с 0.01 на 0.1).
    # Инструмент отчётности обязан давать одно и то же число дважды.
    torch.manual_seed(BOOTSTRAP_SEED)
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        return _fit_pairwise_single_threaded(features, targets, l2)
    finally:
        torch.set_num_threads(threads)


def _fit_pairwise_single_threaded(
    features: torch.Tensor, targets: torch.Tensor, l2: float
) -> torch.Tensor:
    left, right = torch.triu_indices(len(features), len(features), offset=1)
    sign = torch.sign(targets[left] - targets[right])
    keep = sign != 0
    left, right, sign = left[keep], right[keep], sign[keep]
    weights = torch.zeros(features.shape[1], dtype=torch.float32, requires_grad=True)
    optimizer = torch.optim.Adam([weights], lr=PAIRWISE_LR)
    scaled = features.to(torch.float32)
    for _ in range(PAIRWISE_EPOCHS):
        optimizer.zero_grad()
        scores = scaled @ weights
        loss = torch.nn.functional.softplus(
            -sign * (scores[left] - scores[right])
        ).mean() + l2 * weights.pow(2).sum()
        loss.backward()
        optimizer.step()
    return weights.detach().to(torch.float64)


def _bootstrap_difference(
    actual: list[float], left: list[float], right: list[float]
) -> dict[str, float]:
    """95% интервал разницы Spearman парным бутстрапом по сценариям."""

    import random

    from surrogate.crm import spearman

    random.seed(BOOTSTRAP_SEED)
    size = len(actual)
    diffs: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        index = [random.randrange(size) for _ in range(size)]
        sample = [actual[k] for k in index]
        if len(set(sample)) < 3:
            continue
        diffs.append(
            spearman(sample, [left[k] for k in index])
            - spearman(sample, [right[k] for k in index])
        )
    diffs.sort()
    low = diffs[int(0.025 * len(diffs))]
    high = diffs[int(0.975 * len(diffs))]
    return {
        "median": statistics.median(diffs),
        "ci95_low": low,
        "ci95_high": high,
        "replicates": len(diffs),
        "distinguishable": low > 0.0 or high < 0.0,
    }


def _score(
    actual: list[float], predicted: list[float], *, calibrated: bool = True
) -> dict[str, object]:
    """Метрики упорядочивания всегда, метрики величины — только для рублей.

    Ранжировщик и одиночная координата выдают оценку порядка, а не ЧДД:
    R² и MAE на них считаются по величинам разной природы и не значат
    ничего. Показывать «R² = −2150» рядом с «R² = +0.95» нельзя — это
    сравнение несравнимого, поэтому они явно пусты.
    """

    mean = statistics.fmean(actual)
    ss_total = sum((value - mean) ** 2 for value in actual)
    ss_residual = sum((a - p) ** 2 for a, p in zip(actual, predicted, strict=True))
    metrics = ranking_metrics(actual, predicted)
    order = sorted(range(len(predicted)), key=lambda i: predicted[i], reverse=True)
    true_best = max(range(len(actual)), key=lambda i: actual[i])
    return {
        "n_scenarios": len(actual),
        "spearman": metrics.spearman_rank_correlation,
        "true_best_rank": order.index(true_best) + 1,
        "r2": (
            (1.0 - ss_residual / ss_total if ss_total > 0.0 else float("nan"))
            if calibrated
            else None
        ),
        "mae_mln_rub": (
            statistics.fmean(
                abs(a - p) for a, p in zip(actual, predicted, strict=True)
            )
            / 1e6
            if calibrated
            else None
        ),
        "precision_at_k": {str(k): v for k, v in metrics.precision_at_k.items()},
        "regret_at_1_mln_rub": metrics.regret_at_k_rub[1] / 1e6,
    }


def main() -> int:
    args = _parser().parse_args()
    for path, what in ((args.labels, "метки ЧДД"), (args.tensors, "тензорный кеш")):
        if not path.exists():
            raise BaselineError(f"{what} не найдены: {path}")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    bundle = torch.load(args.tensors, map_location="cpu", weights_only=False)

    print("собираю сценарные векторы (train 490 / validation 105 / test 105)…")
    splits = {}
    for split in ("train", "validation", "test"):
        vectors, identities = _vectors(bundle, split)
        splits[split] = (vectors.to(torch.float64), _labels_for(identities, labels))
        print(f"  {split}: {tuple(vectors.shape)}")

    train_x, train_y = splits["train"]
    mean, scale, active = _standardize(train_x)

    def prepare(matrix: torch.Tensor) -> torch.Tensor:
        return ((matrix - mean) / scale)[:, active]

    train_s = prepare(train_x)
    validation_s, validation_y = prepare(splits["validation"][0]), splits["validation"][1]
    test_s, test_y = prepare(splits["test"][0]), splits["test"][1]
    print(f"активных признаков: {int(active.sum())} из {len(active)}")

    # --- ridge: alpha по validation, замер на test ---
    best = None
    for alpha in RIDGE_GRID:
        weights, intercept = _fit_ridge(train_s, train_y, alpha)
        predicted = (validation_s @ weights + intercept).tolist()
        score = _score(validation_y.tolist(), predicted)
        if best is None or score["spearman"] > best[1]["spearman"]:
            best = (alpha, score, weights, intercept)
    alpha, validation_score, weights, intercept = best
    ridge_test = _score(test_y.tolist(), (test_s @ weights + intercept).tolist())
    print(f"\nridge: alpha={alpha:g} выбран по validation (Spearman {validation_score['spearman']:+.4f})")

    # --- попарный ранжировщик ---
    best_pair = None
    for l2 in PAIRWISE_L2_GRID:
        weights_pair = _fit_pairwise(train_s, train_y, l2)
        score = _score(
            validation_y.tolist(),
            (validation_s @ weights_pair).tolist(),
            calibrated=False,
        )
        if best_pair is None or score["spearman"] > best_pair[1]["spearman"]:
            best_pair = (l2, score, weights_pair)
    pair_l2, pair_validation, pair_weights = best_pair
    pairwise_predictions = (test_s @ pair_weights).tolist()
    pairwise_test = _score(test_y.tolist(), pairwise_predictions, calibrated=False)
    print(
        f"pairwise: l2={pair_l2:g} выбран по validation "
        f"(Spearman {pair_validation['spearman']:+.4f})"
    )

    # --- абляция по блокам признакового вектора ---
    ablation: dict[str, object] = {}
    for name, low, high in FEATURE_BLOCKS:
        block_mean, block_scale, block_active = _standardize(train_x[:, low:high])
        block_prepare = lambda m: ((m - block_mean) / block_scale)[:, block_active]
        block_best = None
        for alpha_block in RIDGE_GRID:
            block_weights, block_intercept = _fit_ridge(
                block_prepare(train_x[:, low:high]), train_y, alpha_block
            )
            block_score = _score(
                validation_y.tolist(),
                (
                    block_prepare(splits["validation"][0][:, low:high]) @ block_weights
                    + block_intercept
                ).tolist(),
            )
            if block_best is None or block_score["spearman"] > block_best[1]["spearman"]:
                block_best = (alpha_block, block_score, block_weights, block_intercept)
        alpha_block, block_validation, block_weights, block_intercept = block_best
        ablation[name] = {
            "width": high - low,
            "alpha": alpha_block,
            "validation": block_validation,
            "test": _score(
                test_y.tolist(),
                (
                    block_prepare(splits["test"][0][:, low:high]) @ block_weights
                    + block_intercept
                ).tolist(),
            ),
        }

    # --- одна координата, выбранная по train ---
    centered = train_s - train_s.mean(dim=0)
    target_centered = train_y - train_y.mean()
    correlation = (centered * target_centered.unsqueeze(1)).sum(dim=0) / (
        centered.norm(dim=0) * target_centered.norm() + 1e-12
    )
    index = int(correlation.abs().argmax())
    sign = 1.0 if correlation[index] > 0 else -1.0
    single_test = _score(
        test_y.tolist(), (sign * test_s[:, index]).tolist(), calibrated=False
    )

    # --- GBDT: нелинейная базовая линия из приёмочных гейтов ---
    from sklearn.ensemble import HistGradientBoostingRegressor

    train_active = train_x[:, active].numpy()
    best_gbdt = None
    for leaves, rate, iterations in GBDT_GRID:
        model = HistGradientBoostingRegressor(
            max_leaf_nodes=leaves,
            learning_rate=rate,
            max_iter=iterations,
            early_stopping=False,
            random_state=BOOTSTRAP_SEED,
        )
        model.fit(train_active, train_y.numpy())
        score = _score(
            validation_y.tolist(),
            model.predict(splits["validation"][0][:, active].numpy()).tolist(),
        )
        if best_gbdt is None or score["spearman"] > best_gbdt[1]["spearman"]:
            best_gbdt = ((leaves, rate, iterations), score, model)
    gbdt_params, gbdt_validation, gbdt_model = best_gbdt
    gbdt_predictions = gbdt_model.predict(splits["test"][0][:, active].numpy()).tolist()
    gbdt_test = _score(test_y.tolist(), gbdt_predictions)
    print(
        f"gbdt: leaves={gbdt_params[0]} lr={gbdt_params[1]} iter={gbdt_params[2]} "
        f"выбран по validation (Spearman {gbdt_validation['spearman']:+.4f})"
    )

    # --- калиброванный интервал ЧДД (гейт 6) ---
    # Калибруется на куске train, которого не видела ни модель, ни отбор:
    # validation входит в обучающую популяцию головы, и интервал по ней
    # недокрывает (замер: 80% заявленных → 59% фактических на test).
    generator = torch.Generator().manual_seed(BOOTSTRAP_SEED)
    order = torch.randperm(len(train_x), generator=generator)
    fit_index, calibration_index = order[:390], order[390:]
    interval_mean, interval_scale, interval_active = _standardize(train_x[fit_index])

    def interval_prepare(matrix: torch.Tensor) -> torch.Tensor:
        return ((matrix - interval_mean) / interval_scale)[:, interval_active]

    interval_weights, interval_intercept = _fit_ridge(
        interval_prepare(train_x[fit_index]), train_y[fit_index], alpha
    )

    def interval_predict(matrix: torch.Tensor) -> list[float]:
        return (interval_prepare(matrix) @ interval_weights + interval_intercept).tolist()

    uncertainty: dict[str, object] = {}
    for level in (0.80, 0.90, 0.95):
        conformal = ConformalNpvInterval.fit(
            train_y[calibration_index].tolist(),
            interval_predict(train_x[calibration_index]),
            level=level,
            population="train-holdout-100",
            population_used_in_training=False,
        )
        checks = [
            conformal.check_coverage(
                splits[name][1].tolist(),
                interval_predict(splits[name][0]),
                population=name,
            )
            for name in ("validation", "test")
        ]
        uncertainty[f"{level:.2f}"] = conformal.as_dict(checks)

    # --- production-голова ---
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
    head = env.npv_head
    if head is None:
        raise BaselineError("production-указатель не содержит головы ЧДД")
    production_predictions = head.predict_vectors(splits["test"][0]).tolist()
    production_test = _score(test_y.tolist(), production_predictions)
    ridge_predictions = (test_s @ weights + intercept).tolist()
    differences = {
        "pairwise_minus_production": _bootstrap_difference(
            test_y.tolist(), pairwise_predictions, production_predictions
        ),
        "pairwise_minus_ridge": _bootstrap_difference(
            test_y.tolist(), pairwise_predictions, ridge_predictions
        ),
        "ridge_minus_production": _bootstrap_difference(
            test_y.tolist(), ridge_predictions, production_predictions
        ),
        "production_minus_gbdt": _bootstrap_difference(
            test_y.tolist(), production_predictions, gbdt_predictions
        ),
    }

    payload = {
        "format": FORMAT,
        "provenance": {
            "labels": str(args.labels),
            "labels_sha256": hashlib.sha256(args.labels.read_bytes()).hexdigest(),
            "tensors": str(args.tensors),
            "checkpoint": str(artifacts.checkpoint),
            "npv_head": str(artifacts.npv_head),
            "model_version": env.model.version,
            "split": "test",
            "n_active_features": int(active.sum()),
        },
        "ridge": {
            "alpha": alpha,
            "alpha_selected_on": "validation",
            "validation": validation_score,
            "test": ridge_test,
        },
        "single_feature": {
            "feature_index_in_active": index,
            "train_correlation": float(correlation[index]),
            "test": single_test,
        },
        "pairwise": {
            "l2": pair_l2,
            "l2_selected_on": "validation",
            "validation": pair_validation,
            "test": pairwise_test,
        },
        "gbdt": {
            "max_leaf_nodes": gbdt_params[0],
            "learning_rate": gbdt_params[1],
            "max_iter": gbdt_params[2],
            "selected_on": "validation",
            "validation": gbdt_validation,
            "test": gbdt_test,
        },
        "production": {"test": production_test},
        "block_ablation": ablation,
        "uncertainty": uncertainty,
        "bootstrap_differences": differences,
        "verdict": {
            "any_head_distinguishable": any(
                item["distinguishable"] for item in differences.values()
            ),
            "spearman_gain_over_ridge": production_test["spearman"]
            - ridge_test["spearman"],
            "spearman_gain_over_single_feature": production_test["spearman"]
            - single_test["spearman"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"\n{'модель':18} {'Spearman':>10} {'место 1-го':>11} {'R²':>9} {'MAE, млн':>10}")
    for name, table in (
        ("одна координата", single_test),
        ("ridge", ridge_test),
        ("попарный", pairwise_test),
        ("GBDT", gbdt_test),
        ("production", production_test),
    ):
        r2 = f"{table['r2']:+9.4f}" if table["r2"] is not None else "        —"
        mae = (
            f"{table['mae_mln_rub']:10.1f}"
            if table["mae_mln_rub"] is not None
            else "         —"
        )
        print(
            f"{name:18} {table['spearman']:>+10.4f} {table['true_best_rank']:>11} {r2} {mae}"
        )
    print(f"\n{'абляция блоков признаков':26} {'ширина':>7} {'Spearman test':>14}")
    for name, table in ablation.items():
        print(f"{name:26} {table['width']:>7} {table['test']['spearman']:>+14.4f}")

    print(f"\n{'парная разница Spearman':30} {'медиана':>9} {'95% ДИ':>22} вердикт")
    for name, item in differences.items():
        verdict = "ОТЛИЧИМ" if item["distinguishable"] else "в пределах шума"
        interval = f"[{item['ci95_low']:+.4f}; {item['ci95_high']:+.4f}]"
        print(f"{name:30} {item['median']:>+9.4f} {interval:>22} {verdict}")

    print(f"\n{'интервал ЧДД':>13} {'полуширина, млн':>16} {'покрытие val':>13} {'покрытие test':>14}")
    for name, item in uncertainty.items():
        measured = {c["population"]: c["coverage"] for c in item["measured_coverage"]}
        print(
            f"{float(name):>12.0%} {item['half_width_mln_rub']:>16.1f} "
            f"{measured['validation']:>12.1%} {measured['test']:>13.1%}"
        )

    if not payload["verdict"]["any_head_distinguishable"]:
        print(
            "\nВывод: ни одна голова не отличима от остальных на 105 сценариях. "
            "Узкое место — представление признаков, а не регрессор."
        )
    print(f"отчёт: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
