"""Ранг траекторной модели против фактического ЧДД — проверка §9.4.

`ranking_loss_weight` и `target_parameterization` замерены как несовместимые:
коммит `820345a` отключил контрактную параметризацию целей, потому что в паре
с ранговым лоссом она дала Spearman −0.278 на тесте при ранге +0.930 на
валидации. Диагноз был такой: ранговый лосс поднимает сценарии через
обводнённость, минуя статьи ЧДД, которых нет в денежном прокси.

Проверить это можно только обучением, и до сих пор было нечем: тензорный
тренер не давал менять параметризацию, а ретензоризация требовала сырых
чанков. Оба препятствия сняты — цели под обводнённость выводятся из уже
сохранённых чистой формулой (`tools/surrogate_watercut_tensors.py`).

Инструмент считает то, что показывает пригодность, а не сходимость:
**ранговую корреляцию денежного прокси модели с фактическим ЧДД** на тесте.
Ранг внутри обучения меряет прокси против прокси и обе стороны может увести
одинаково; здесь одна сторона — метки из настоящих прогонов OPM.

Запуск:

    PYTHONPATH=. python tools/surrogate_parameterization_eval.py \\
        --checkpoint data/model-night-20260826-v2/physical/model.pt \\
        --tensors data/lean700/tensors_context_490_canonical.pt \\
        --output data/surrogate/parameterization.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch

from economics import load_normatives
from optimizer.search_run import NORMATIVES
from surrogate.crm import spearman
from surrogate.model import TrajectorySurrogate, _scenario_money
from surrogate.train import money_rub_per_unit

DEFAULT_LABELS = Path("data/model-night-20260826-v2/npv_labels.json")
FORMAT = "aios.surrogate-parameterization-eval.v1"
INFERENCE_BATCH = 32768


class EvalError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, action="append", required=True)
    parser.add_argument("--tensors", type=Path, action="append", required=True)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--split", default="test")
    parser.add_argument("--output", type=Path, required=True)
    return parser


@torch.no_grad()
def _scenario_scores(
    model: TrajectorySurrogate, bundle: dict, split: str, rub: tuple[float, ...]
) -> list[float]:
    """Денежный прокси сценария по прогнозу модели, в порядке идентичностей."""

    identities = bundle["identities"][split]
    x, well_index, _ = bundle["tensors"][split]
    width = len(model.input_scaler.mean)
    if x.shape[1] < width:
        raise EvalError(
            f"тензоры дают {x.shape[1]} признаков, модель ждёт {width}"
        )
    x = x[:, :width]
    scaled = model.input_scaler.transform(x)
    model.network.eval()
    chunks = [
        model.network(
            scaled[start : start + INFERENCE_BATCH],
            well_index[start : start + INFERENCE_BATCH],
        )
        for start in range(0, len(scaled), INFERENCE_BATCH)
    ]
    standardized = torch.cat(chunks)
    per_scenario = len(x) // len(identities)
    scenario_index = torch.arange(len(x)) // per_scenario
    money = _scenario_money(
        standardized,
        scenario_index,
        len(identities),
        # `Standardizer` хранит кортежи, а `_scenario_money` ждёт тензоры.
        scale=torch.tensor(model.target_scaler.scale, dtype=standardized.dtype),
        mean=torch.tensor(model.target_scaler.mean, dtype=standardized.dtype),
        rub_per_unit=torch.tensor(rub, dtype=standardized.dtype),
        parameterization=model.config.target_parameterization,
        oil_density_t_per_m3=model.config.oil_density_t_per_m3,
    )
    return money.tolist()


def main() -> int:
    args = _parser().parse_args()
    if len(args.checkpoint) != len(args.tensors):
        raise EvalError("каждому чекпоинту нужен свой тензорный артефакт")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    by_hash = {row["canonical_schedule_hash"]: row for row in labels["rows"].values()}
    rub = money_rub_per_unit(load_normatives(NORMATIVES))

    rows = []
    for checkpoint, tensors in zip(args.checkpoint, args.tensors, strict=True):
        bundle = torch.load(tensors, map_location="cpu", weights_only=False)
        model = TrajectorySurrogate.load(checkpoint)
        identities = bundle["identities"][args.split]
        actual = []
        for identity in identities:
            row = by_hash.get(identity["canonical_schedule_hash"])
            if row is None:
                raise EvalError(f"нет метки ЧДД для {identity['scenario_id']}")
            actual.append(float(row["npv_rub"]))
        scores = _scenario_scores(model, bundle, args.split, rub)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        true_best = max(range(len(actual)), key=lambda i: actual[i])
        rows.append(
            {
                "checkpoint": str(checkpoint),
                "tensors": str(tensors),
                "target_parameterization": model.config.target_parameterization,
                "ranking_loss_weight": model.config.ranking_loss_weight,
                "scenario_context": str(model.config.scenario_context),
                "version": model.version,
                "n_scenarios": len(actual),
                "spearman_proxy_vs_true_npv": spearman(actual, scores),
                "true_best_rank": order.index(true_best) + 1,
            }
        )
        print(
            f"{checkpoint.parent.name + '/' + checkpoint.name:44} "
            f"{model.config.target_parameterization:9} "
            f"rank_w={model.config.ranking_loss_weight:<4g} "
            f"Spearman {rows[-1]['spearman_proxy_vs_true_npv']:+.4f}  "
            f"истинный лучший на {rows[-1]['true_best_rank']} из {len(actual)}"
        )

    payload = {
        "format": FORMAT,
        "split": args.split,
        "labels": str(args.labels),
        "metric": "Spearman(денежный прокси модели, фактический ЧДД OPM)",
        "runs": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nотчёт: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
