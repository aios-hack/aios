from __future__ import annotations

from backend.contexts.optimization.application.search_use_case import (
    BASE_NPV,
    BUDGET,
    BhpTolerance,
    BhpToleranceError,
    CONSTRAINTS,
    ConnectivitySearchError,
    FINALIST_CAP,
    FINAL_CAP,
    IncumbentRegistry,
    MISSING_SIGMA,
    OpmBudgetError,
    RESPONSE,
    RISK_AVERSION_BETA,
    RunBudget,
    SEARCH_CAP,
    SEARCH_DIAGNOSTICS,
    SEARCH_RESULT,
    SEED,
    SURROGATE_METRICS_FORMAT,
    SearchOutcome,
    SearchRunError,
    bhp_exceedance_bar,
    candidate_card,
    close_run_clock,
    incumbent_gate_passed,
    main,
    read_opm_budget,
    run_search,
    select_finalist,
    start_run_clock,
    surrogate_blocking_violations,
)
from backend.contexts.optimization.domain.gates.bhp_tolerance import (
    BHP_KINDS,
    DEFAULT_SURROGATE_METRICS,
    SURROGATE_NONBLOCKING_KINDS,
)
from backend.contexts.optimization.domain.gates.incumbent import (
    IncumbentRecord,
)
from backend.contexts.optimization.domain.gates.ood_threshold import (
    CONSERVATIVE_OOD_THRESHOLD,
    DEFAULT_OOD_CALIBRATION,
    OOD_CALIBRATION_FORMAT,
    OodThreshold,
)
from backend.contexts.optimization.domain.gates.opm_budget import (
    OPM_BUDGET_JOURNAL,
    RUN_CLOCK,
    measure_run_budget,
)
from backend.contexts.optimization.domain.search_limits import (
    DEFAULT_FINAL_CAP,
    DEFAULT_SEARCH_CAP,
    INJECTION_TRANSFER_STEPS_M3_PER_DAY,
    WATER_REPAIR_CEILING,
    WATER_REPAIR_MARGIN,
)


if __name__ == "__main__":
    from backend.contexts.optimization.application.search_use_case import main as _main

    raise SystemExit(_main())


__all__ = [
    "BASE_NPV",
    "BHP_KINDS",
    "BUDGET",
    "BhpTolerance",
    "BhpToleranceError",
    "CONSERVATIVE_OOD_THRESHOLD",
    "CONSTRAINTS",
    "ConnectivitySearchError",
    "DEFAULT_FINAL_CAP",
    "DEFAULT_OOD_CALIBRATION",
    "DEFAULT_SEARCH_CAP",
    "DEFAULT_SURROGATE_METRICS",
    "FINALIST_CAP",
    "FINAL_CAP",
    "INJECTION_TRANSFER_STEPS_M3_PER_DAY",
    "IncumbentRecord",
    "IncumbentRegistry",
    "MISSING_SIGMA",
    "OOD_CALIBRATION_FORMAT",
    "OPM_BUDGET_JOURNAL",
    "OodThreshold",
    "OpmBudgetError",
    "RESPONSE",
    "RISK_AVERSION_BETA",
    "RUN_CLOCK",
    "RunBudget",
    "SEARCH_CAP",
    "SEARCH_DIAGNOSTICS",
    "SEARCH_RESULT",
    "SEED",
    "SURROGATE_METRICS_FORMAT",
    "SURROGATE_NONBLOCKING_KINDS",
    "SearchOutcome",
    "SearchRunError",
    "WATER_REPAIR_CEILING",
    "WATER_REPAIR_MARGIN",
    "bhp_exceedance_bar",
    "candidate_card",
    "close_run_clock",
    "incumbent_gate_passed",
    "main",
    "measure_run_budget",
    "read_opm_budget",
    "run_search",
    "select_finalist",
    "start_run_clock",
    "surrogate_blocking_violations",
]
