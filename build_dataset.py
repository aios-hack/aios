from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from backend.infrastructure.opm.dataset import DatasetGenerator
from backend.infrastructure.opm.dataset_plan import build_plan
from backend.infrastructure.resources import model_z_dir

SEED = 20260816
ROOT = Path(os.environ.get("AIOS_DATASET_ROOT", "w:/Projects/hacks/aios/data/dataset-main"))
WORKERS = int(os.environ.get("AIOS_DATASET_WORKERS", "4"))


def main() -> int:
    try:
        model_z = model_z_dir()
    except FileNotFoundError as error:
        print(error, flush=True)
        return 2
    ROOT.mkdir(parents=True, exist_ok=True)
    generator = DatasetGenerator(
        model_z, ROOT, max_workers=WORKERS, timeout_seconds=7200.0
    )
    plan = build_plan(generator.base_schedule(), seed=SEED)
    print(f"сценариев в плане: {len(plan)}, воркеров: {WORKERS}", flush=True)
    started = time.monotonic()
    report = generator.build(plan)
    elapsed = time.monotonic() - started
    print(
        f"готово за {elapsed / 60:.1f} мин: "
        f"посчитано {report.n_simulated}, из кеша {report.n_from_cache}, "
        f"пропущено {len(report.skipped)}, упало {len(report.failed)}",
        flush=True,
    )
    for item in report.failed:
        print(f"  FAILED {item.message}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
