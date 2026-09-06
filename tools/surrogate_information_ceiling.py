"""Абляция признаков достижимости на фиксированном представлении расписания.

Отвечает на вопрос, который иначе решается спорами: стоит ли вкладываться в
новые признаки суррогата или нужны новые прогоны OPM.

Метод — разделить два вида «признака достижимости уставки»:

* **оракульный** — недобор `max(0, уставка − фактический дебит)`, посчитанный
  по **настоящему отклику OPM**. На инференсе недоступен: это утечка ответа;
* **предсказанный** — тот же недобор, но по прогнозу траекторного ансамбля.
  Доступен всегда, потому что ансамбль ест только признаки расписания.

Если оракульный помогает, а предсказанный нет, значит выигрыш даёт не
«достижимость», а знание отклика. Предсказанный недобор — детерминированная
функция тех же признаков, новой информации в нём нет по построению, и
линейная модель может выиграть только от нелинейности этой функции.

Замеренный результат (105 сценариев test, гребневая регрессия):

| Признаки | Spearman | Медиана ошибки | Верхняя четверть |
|---|---|---|---|
| 4406 сценарных | +0.8380 | 30.1 млн ₽ | 59.7 млн ₽ |
| + 5 оракульных | +0.8425 | 23.7 | 49.5 |
| + 5 предсказанных | +0.8357 | 30.3 | 59.7 |

При том что предсказание достижимости само по себе отличное: поузловой
`liquid_rate` добывающих совпадает с фактом на Spearman +0.977 при MAE
0.94 м³/сут против среднего факта 22.20.

Вывод ограничен этими вариантами. Опыт не доказывает достаточность
представления и не устанавливает универсальный информационный потолок.

Запуск:

    PYTHONPATH=. python tools/surrogate_information_ceiling.py \\
        --output data/surrogate/information-ceiling.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch

from surrogate.crm import spearman
from surrogate.ensemble import TrajectoryEnsemble
from surrogate.npv_head import scenario_feature_vector

FORMAT = "aios.surrogate-information-ceiling.v1"
DEFAULT_TENSORS = Path("data/lean700/tensors_context_490_canonical.pt")
DEFAULT_LABELS = Path("data/model-night-20260826-v2/npv_labels.json")
DEFAULT_ENSEMBLE = Path("data/model-night-20260826-v2/physical/trajectory_ensemble.json")
RIDGE_GRID: tuple[float, ...] = (1e-3, 1e-2, 1e-1, 1.0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6)
INFERENCE_BATCH = 32768

# Раскладка `_node_vector` (`surrogate/model.py`): восемь числовых признаков в
# log1p, затем статика, доля шага и одно-горячие роли. Индексы совпадают с теми,
# что читает `npv_head._economic_event_vector`.
COLUMN_SETPOINT = 0
COLUMN_AVAILABLE = 15
COLUMN_PRODUCER = 17
COLUMN_INJECTOR = 18
COLUMN_OPEN = 19
NODE_FEATURE_WIDTH = 21  # вход ансамбля: scenario_context в production выключен

# Индексы каналов в `TARGET_NAMES`.
TARGET_LIQUID_RATE = 3
TARGET_INJECTION_RATE = 4

SHORTFALL_NAMES: tuple[str, ...] = (
    "shortfall_total",
    "shortfall_per_active_node",
    "shortfall_relative_mean",
    "share_of_nodes_below_95pct",
    "worst_node_relative",
)
# Узел считается недобирающим, если фактический дебит ниже уставки более чем
# на 5%: ниже этого порога расхождение неотличимо от округления уставки.
SHORTFALL_THRESHOLD = 0.05


class CeilingError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tensors", type=Path, default=DEFAULT_TENSORS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--ensemble", type=Path, default=DEFAULT_ENSEMBLE)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _shortfall_row(
    node_features: torch.Tensor, actual_rate: torch.Tensor
) -> list[float]:
    """Пять агрегатов недобора уставки по узлам одного сценария."""

    setpoint = torch.expm1(node_features[:, COLUMN_SETPOINT])
    producer = node_features[:, COLUMN_PRODUCER] > 0.5
    injector = node_features[:, COLUMN_INJECTOR] > 0.5
    is_open = node_features[:, COLUMN_OPEN] > 0.5
    active = (producer | injector) & is_open & (setpoint > 0)
    shortfall = torch.clamp(setpoint - actual_rate, min=0.0) * active
    relative = torch.where(
        active, shortfall / setpoint.clamp_min(1e-6), torch.zeros_like(shortfall)
    )
    n_active = active.sum().clamp_min(1).to(torch.float64)
    return [
        shortfall.sum().item(),
        (shortfall.sum() / n_active).item(),
        relative.sum().item() / n_active.item(),
        ((relative > SHORTFALL_THRESHOLD) & active).sum().item() / n_active.item(),
        relative.max().item(),
    ]


def _rate_from(
    node_features: torch.Tensor, channels: torch.Tensor, *, already_physical: bool
) -> torch.Tensor:
    """Дебит, релевантный роли узла: жидкость у добывающей, приёмистость у нагнетательной."""

    liquid = channels[:, TARGET_LIQUID_RATE]
    injection = channels[:, TARGET_INJECTION_RATE]
    if not already_physical:
        liquid, injection = torch.expm1(liquid), torch.expm1(injection)
    producer = node_features[:, COLUMN_PRODUCER] > 0.5
    injector = node_features[:, COLUMN_INJECTOR] > 0.5
    return torch.where(
        producer, liquid, torch.where(injector, injection, torch.zeros_like(liquid))
    )


@torch.no_grad()
def _ensemble_decode(
    ensemble: TrajectoryEnsemble, x: torch.Tensor, well_index: torch.Tensor
) -> torch.Tensor:
    """Взвешенное среднее ансамбля в физических единицах."""

    total: torch.Tensor | None = None
    for model, weight in zip(ensemble.models, ensemble.weights, strict=True):
        model.network.eval()
        scaled = model.input_scaler.transform(x)
        chunks = [
            model.network(
                scaled[start : start + INFERENCE_BATCH],
                well_index[start : start + INFERENCE_BATCH],
            )
            for start in range(0, len(scaled), INFERENCE_BATCH)
        ]
        decoded = torch.expm1(
            model.target_scaler.inverse(torch.cat(chunks))
        ).clamp_min(0.0)
        total = decoded * weight if total is None else total + decoded * weight
    if total is None:
        raise CeilingError("ансамбль пуст")
    return total


def _fit_ridge_select(
    train: torch.Tensor,
    train_y: torch.Tensor,
    validation: torch.Tensor,
    validation_y: torch.Tensor,
) -> tuple[float, "callable"]:
    mean = train.mean(dim=0)
    scale = train.std(dim=0, unbiased=False)
    active = scale > 1e-9
    scale = torch.where(active, scale, torch.ones_like(scale))

    def prepare(matrix: torch.Tensor) -> torch.Tensor:
        return ((matrix - mean) / scale)[:, active]

    prepared = prepare(train)
    best = None
    for alpha in RIDGE_GRID:
        gram = prepared.T @ prepared + alpha * torch.eye(
            prepared.shape[1], dtype=prepared.dtype
        )
        weights = torch.linalg.solve(gram, prepared.T @ (train_y - train_y.mean()))
        score = spearman(
            validation_y.tolist(),
            (prepare(validation) @ weights + train_y.mean()).tolist(),
        )
        if best is None or score > best[0]:
            best = (score, alpha, weights)
    _, alpha, weights = best
    return alpha, lambda matrix: prepare(matrix) @ weights + train_y.mean()


def main() -> int:
    args = _parser().parse_args()
    for path, what in (
        (args.tensors, "тензорный кеш"),
        (args.labels, "метки ЧДД"),
        (args.ensemble, "траекторный ансамбль"),
    ):
        if not path.exists():
            raise CeilingError(f"{what} не найден: {path}")

    bundle = torch.load(args.tensors, map_location="cpu", weights_only=False)
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    by_hash = {row["canonical_schedule_hash"]: row for row in labels["rows"].values()}
    ensemble = TrajectoryEnsemble.load(args.ensemble)
    n_wells = len(bundle["wells"])

    scenario: dict[str, torch.Tensor] = {}
    oracle: dict[str, torch.Tensor] = {}
    predicted: dict[str, torch.Tensor] = {}
    targets: dict[str, torch.Tensor] = {}
    per_node_quality: dict[str, float] = {}

    for split in ("train", "validation", "test"):
        identities = bundle["identities"][split]
        x, well_index, y = bundle["tensors"][split]
        per_scenario = len(x) // len(identities)
        print(f"{split}: {len(identities)} сценариев…")

        vectors, oracle_rows, predicted_rows, npv = [], [], [], []
        for index, identity in enumerate(identities):
            start = index * per_scenario
            stop = start + per_scenario
            nodes = x[start:stop]
            vectors.append(
                scenario_feature_vector(
                    nodes, well_index[start:stop], n_wells=n_wells, feature_set="economic"
                )
            )
            oracle_rows.append(
                _shortfall_row(
                    nodes, _rate_from(nodes, y[start:stop], already_physical=False)
                )
            )
            decoded = _ensemble_decode(
                ensemble, nodes[:, :NODE_FEATURE_WIDTH], well_index[start:stop]
            )
            predicted_rows.append(
                _shortfall_row(nodes, _rate_from(nodes, decoded, already_physical=True))
            )
            row = by_hash.get(identity["canonical_schedule_hash"])
            if row is None:
                raise CeilingError(f"нет метки ЧДД для {identity['scenario_id']}")
            npv.append(float(row["npv_rub"]))
            if split == "test" and index < 20:
                producer = nodes[:, COLUMN_PRODUCER] > 0.5
                per_node_quality.setdefault("_actual", [])  # type: ignore[arg-type]
                per_node_quality["_actual"] = per_node_quality.get("_actual", []) + torch.expm1(  # type: ignore[operator]
                    y[start:stop][:, TARGET_LIQUID_RATE]
                )[producer].tolist()
                per_node_quality["_predicted"] = per_node_quality.get(
                    "_predicted", []
                ) + decoded[:, TARGET_LIQUID_RATE][producer].tolist()  # type: ignore[operator]

        scenario[split] = torch.stack(vectors).to(torch.float64)
        oracle[split] = torch.tensor(oracle_rows, dtype=torch.float64)
        predicted[split] = torch.tensor(predicted_rows, dtype=torch.float64)
        targets[split] = torch.tensor(npv, dtype=torch.float64)

    actual_nodes = per_node_quality["_actual"]  # type: ignore[index]
    predicted_nodes = per_node_quality["_predicted"]  # type: ignore[index]
    node_quality = {
        "population": "добывающие узлы первых 20 сценариев test",
        "n_nodes": len(actual_nodes),
        "spearman": spearman(actual_nodes, predicted_nodes),
        "mae_m3_per_day": statistics.fmean(
            abs(a - p) for a, p in zip(actual_nodes, predicted_nodes, strict=True)
        ),
        "mean_actual_m3_per_day": statistics.fmean(actual_nodes),
    }

    variants = {
        "scenario_only": lambda split: scenario[split],
        "oracle_only": lambda split: oracle[split],
        "predicted_only": lambda split: predicted[split],
        "scenario_plus_oracle": lambda split: torch.cat(
            [scenario[split], oracle[split]], dim=1
        ),
        "scenario_plus_predicted": lambda split: torch.cat(
            [scenario[split], predicted[split]], dim=1
        ),
    }

    results: dict[str, object] = {}
    worst_quartile = _worst_quartile_index(oracle["test"])
    for name, build in variants.items():
        alpha, predict = _fit_ridge_select(
            build("train"), targets["train"], build("validation"), targets["validation"]
        )
        prediction = predict(build("test"))
        errors = (targets["test"] - prediction).abs()
        results[name] = {
            "alpha": alpha,
            "spearman_test": spearman(targets["test"].tolist(), prediction.tolist()),
            "median_error_mln_rub": float(errors.median()) / 1e6,
            "worst_quartile_median_error_mln_rub": statistics.median(
                errors[k].item() for k in worst_quartile
            )
            / 1e6,
        }

    agreement = {
        name: spearman(oracle["test"][:, i].tolist(), predicted["test"][:, i].tolist())
        for i, name in enumerate(SHORTFALL_NAMES)
    }

    ceiling = (
        results["scenario_plus_oracle"]["median_error_mln_rub"]  # type: ignore[index]
        < results["scenario_plus_predicted"]["median_error_mln_rub"]  # type: ignore[index]
    )
    payload = {
        "format": FORMAT,
        "provenance": {
            "tensors": str(args.tensors),
            "labels": str(args.labels),
            "ensemble": str(args.ensemble),
            "ensemble_version": ensemble.version,
        },
        "variants": results,
        "shortfall_agreement_spearman": agreement,
        "per_node_rate_quality": node_quality,
        "verdict": {
            "oracle_beats_predicted": ceiling,
            "conclusion": (
                "выигрыш даёт знание отклика, а не признак достижимости: "
                "предсказанный недобор — функция тех же признаков расписания"
                if ceiling
                else "предсказанный недобор догоняет оракульный — признак стоит внедрять"
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"\n{'набор признаков':28} {'Spearman test':>13} {'медиана ошибки':>15} {'верх. четверть':>15}")
    for name, table in results.items():
        print(
            f"{name:28} {table['spearman_test']:>+13.4f} "
            f"{table['median_error_mln_rub']:>14.1f}м {table['worst_quartile_median_error_mln_rub']:>14.1f}м"
        )

    print(f"\nсовпадение предсказанного недобора с фактическим (Spearman на test):")
    for name, value in agreement.items():
        print(f"  {name:28} {value:+.4f}")
    print(
        f"\nпоузловой дебит добывающих: Spearman {node_quality['spearman']:+.4f}, "
        f"MAE {node_quality['mae_m3_per_day']:.2f} м³/сут "
        f"при среднем факте {node_quality['mean_actual_m3_per_day']:.2f}"
    )
    print(f"\n{payload['verdict']['conclusion']}")
    print(f"отчёт: {args.output}")
    return 0


def _worst_quartile_index(oracle_test: torch.Tensor) -> list[int]:
    """Четверть сценариев с наибольшей фактической недостачей уставок."""

    column = oracle_test[:, SHORTFALL_NAMES.index("shortfall_relative_mean")]
    order = sorted(range(len(column)), key=lambda k: float(column[k]))
    return order[-max(1, len(order) // 4) :]


if __name__ == "__main__":
    raise SystemExit(main())
