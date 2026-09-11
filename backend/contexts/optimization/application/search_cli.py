from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.contexts.optimization.application.search_config import (
    BASE_NPV,
    BUDGET,
    FINAL_CAP,
    SEARCH_CAP,
    SEARCH_RESULT,
    SEED,
)
from backend.contexts.optimization.application.search_use_case import run_search
from backend.shared.hashing import canonical_bytes


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else BUDGET
    case_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    outcome = run_search(budget=budget, case_path=case_path)
    out = SEARCH_RESULT
    schedule_path = out.with_name('cmaes-schedule.json')
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_bytes(canonical_bytes(outcome.schedule))
    out.write_text(
        json.dumps(
            {
                "seed": SEED,
                "schedule_path": str(schedule_path),
                "budget": budget,
                "evaluations": outcome.evaluations,
                "search_cap": int(
                    outcome.provenance.get("search_fixed_point_cap", SEARCH_CAP)
                ),
                "final_cap": int(
                    outcome.provenance.get("final_fixed_point_cap", FINAL_CAP)
                ),
                "theta": dict(outcome.theta.values),
                "npv_predicted": outcome.predicted_npv,
                "npv_baseline": BASE_NPV,
                "canonical_schedule_hash": outcome.schedule_hash,
                "static_violations": outcome.static_violations,
                "dynamic_blocking_violations": outcome.dynamic_blocking_violations,
                "converged": outcome.converged,
                "self_consistent": outcome.self_consistent,
                "incumbents": [
                    record.as_dict() for record in outcome.incumbent_history
                ],
                **(
                    {
                        "wallclock_seconds": None,
                        "surrogate_evaluations": None,
                        "opm_runs": None,
                        "opm_runs_source": None,
                        "opm_wallclock_seconds": None,
                    }
                    if getattr(outcome, "budget", None) is None
                    else outcome.budget.as_dict()
                ),
                "provenance": outcome.provenance,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"result written: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
