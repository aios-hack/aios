"""Пункт 1 запросов Андрея: A/B денежного взвешивания лосса на 700 прогонах.

Двумя вызовами `surrogate/train.py` это не делается: он строит план на 199
сценариев, то есть только пилотную часть. Сплит 490/105/105 живёт на
объединённых 700, и собирает его `surrogate/cycle.py::_train_combined`, где
флагов денежного лосса нет. Здесь тот же комбинированный путь с двумя
конфигами.

**Датасет собирается один раз на обе руки.** Отклики 700 прогонов — около
15 ГБ, и вторая сборка ради второй руки удвоила бы пик памяти впустую:
`money_weight_alpha` меняет вес элемента лосса, а не признаки и не цели, так
что примеры обучения у рук побитово одни и те же. По той же причине сырые
отклики train и validation отпускаются сразу после featureize: дальше нужны
только тензоры. Тестовые остаются — на них считается `evaluate`.

Руки: alpha=0 (`alpha·w + (1−alpha)` вырождается в равномерный smooth_l1,
то есть поведение опубликованного чекпоинта) против alpha=0.7.

Запуск: `PYTHONPATH=. python tools/ab_money_loss.py [эпох] [терпение]`.
"""

from __future__ import annotations

import gc
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import conftest
from backend.domain.economics import load_normatives
from backend.ml.surrogate.cycle import EXTRA_CONFIG, PILOT_CONFIG, _build_stage, _combined_hash
from backend.ml.surrogate.model import ModelConfig, TrajectorySurrogate
from backend.ml.surrogate.model_z_context import build_model_z_context
from backend.ml.surrogate.train import _examples, evaluate, money_rub_per_unit, split_samples

DATA_ROOT = Path("data")
OUT_ROOT = Path("data/ab-money-loss")
SEED = 20260817
EPOCHS = int(sys.argv[1]) if len(sys.argv) > 1 else 80
PATIENCE = int(sys.argv[2]) if len(sys.argv) > 2 else 10
WORKERS = 8


def _rss_gb() -> float:
    import resource

    # ru_maxrss на macOS в байтах, на Linux в килобайтах.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024**3) if sys.platform == "darwin" else peak / (1024**2)


def main() -> int:
    model_dir = conftest.model_z_dir()
    normatives_path = conftest.chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    normatives = load_normatives(normatives_path)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    print("сборка пилотных 200...", flush=True)
    started = time.monotonic()
    pilot = _build_stage(
        model_dir=model_dir,
        root=DATA_ROOT / "dataset-main",
        seed=SEED,
        config=PILOT_CONFIG,
        workers=WORKERS,
    )
    print(f"  {len(pilot.samples)} сценариев за {(time.monotonic() - started) / 60:.1f} мин, "
          f"пик памяти {_rss_gb():.1f} ГБ", flush=True)

    print("сборка дополнительных 500...", flush=True)
    started = time.monotonic()
    extra = _build_stage(
        model_dir=model_dir,
        root=DATA_ROOT / "dataset-extra-500",
        seed=SEED,
        config=EXTRA_CONFIG,
        workers=WORKERS,
    )
    print(f"  {len(extra.samples)} сценариев за {(time.monotonic() - started) / 60:.1f} мин, "
          f"пик памяти {_rss_gb():.1f} ГБ", flush=True)

    dataset_hash = _combined_hash(pilot, extra)
    samples = tuple(pilot.samples) + tuple(extra.samples)
    source_hashes = [pilot.dataset_hash, extra.dataset_hash]
    source_plans = [pilot.plan_hash, extra.plan_hash]
    del pilot, extra
    gc.collect()
    print(f"объединено {len(samples)} сценариев, hash {dataset_hash[:12]}…", flush=True)

    split = split_samples(samples, validation_fraction=0.15, test_fraction=0.15, seed=SEED)
    del samples
    gc.collect()
    print(
        f"сплит: train {len(split.train)}, validation {len(split.validation)}, "
        f"test {len(split.test)}",
        flush=True,
    )

    context = build_model_z_context(model_dir, split.train, dataset_hash=dataset_hash)
    context.save(OUT_ROOT / "feature_context.json")
    print(f"контекст построен, пик памяти {_rss_gb():.1f} ГБ", flush=True)

    train = _examples(split.train, context)
    validation = _examples(split.validation, context)
    test = _examples(split.test, context)
    test_samples = tuple(split.test)
    # Сырые отклики train и validation больше не нужны: обучение идёт по
    # тензорам. Держать их до конца — это те самые лишние гигабайты, из-за
    # которых прогон убивается системой на машине с 24 ГБ.
    del split
    gc.collect()
    print(f"признаки готовы, пик памяти {_rss_gb():.1f} ГБ", flush=True)

    arms = (
        ("base", 0.0),
        ("money", 0.7),
    )
    results: dict[str, dict] = {}
    for name, alpha in arms:
        output_dir = OUT_ROOT / f"model-ab-{name}"
        output_dir.mkdir(parents=True, exist_ok=True)
        settings = ModelConfig(
            hidden_width=128,
            hidden_layers=3,
            batch_size=32768,
            max_epochs=EPOCHS,
            patience=PATIENCE,
            seed=SEED,
            money_rub_per_unit=money_rub_per_unit(normatives),
            money_weight_alpha=alpha,
            money_weight_cap=50.0,
            lr_schedule="none",
            select_by="loss",
            target_parameterization="absolute",
        )
        print(f"\n=== рука {name}: money_weight_alpha={alpha} ===", flush=True)
        started = time.monotonic()
        best = {"epoch": 0, "loss": float("inf")}

        def on_epoch(item, best=best) -> None:
            if item.validation_loss < best["loss"]:
                best["loss"] = item.validation_loss
                best["epoch"] = item.epoch
            if item.epoch % 5 == 0 or item.epoch == 1:
                print(
                    f"  эпоха {item.epoch:3d}: train {item.train_loss:.6f} "
                    f"validation {item.validation_loss:.6f} "
                    f"(лучшая {best['epoch']})",
                    flush=True,
                )

        result = TrajectorySurrogate.fit(
            train,
            validation,
            config=settings,
            dataset_hash=dataset_hash,
            device="cpu",
            epoch_callback=on_epoch,
        )
        elapsed = time.monotonic() - started
        result.model.save(output_dir / "model.pt")
        context.save(output_dir / "feature_context.json")
        print(f"  обучение за {elapsed / 60:.1f} мин, пик памяти {_rss_gb():.1f} ГБ", flush=True)

        metrics = evaluate(
            result.model,
            test,
            test_samples,
            context,
            model_schedule_path=model_dir / "Model_Z_sch.inc",
            normatives_path=normatives_path,
            oil_density_t_per_m3=0.9131,
        )
        report = {
            "format": "aios.surrogate-ab-training-report.v1",
            "arm": name,
            "money_weight_alpha": alpha,
            "dataset_hash": dataset_hash,
            "source_dataset_hashes": source_hashes,
            "source_plan_hashes": source_plans,
            "model_version": result.model.version,
            "seed": SEED,
            "epochs": EPOCHS,
            "patience": PATIENCE,
            "best_epoch": best["epoch"],
            "best_validation_loss": best["loss"],
            "training_seconds": elapsed,
            "history": [asdict(item) for item in result.history],
            "metrics": asdict(metrics) if hasattr(metrics, "__dataclass_fields__") else metrics,
        }
        (output_dir / "training_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        results[name] = report
        print(f"  отчёт: {output_dir / 'training_report.json'}", flush=True)
        del result
        gc.collect()

    print("\n=== A/B ===", flush=True)
    print(json.dumps({k: v.get("best_validation_loss") for k, v in results.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
