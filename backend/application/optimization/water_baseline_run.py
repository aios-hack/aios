from __future__ import annotations

from backend.contexts.optimization.application.water_baseline_run import (
    ACTIVE_CALIBRATION,
    WATER_SAFETY_FACTOR,
    WORK_ROOT,
    main,
)


if __name__ == "__main__":
    from backend.contexts.optimization.application.water_baseline_run import main as _main

    raise SystemExit(_main())


__all__ = [
    "ACTIVE_CALIBRATION",
    "WATER_SAFETY_FACTOR",
    "WORK_ROOT",
    "main",
]
