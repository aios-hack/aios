from __future__ import annotations

from typing import Sequence

from backend.contexts.connectivity.domain.fund import ActiveFund, Window
from backend.contexts.connectivity.domain.hadamard import hadamard, is_hadamard, normalized

from backend.contexts.connectivity.domain.doe_plan import (
    LEVEL_HIGH,
    LEVEL_LOW,
    RUN_BLOCK,
    Amplitude,
    DoEPlan,
    Level,
    PlanRow,
    amplitude_from_prior,
    plan_runs,
)
from backend.contexts.connectivity.domain.doe_diagnostics import (
    AchievabilityCheck,
    AchievabilityReport,
    Orthogonality,
    achievability,
    orthogonality_of,
    realized_matrix,
)

__all__ = [
    "LEVEL_HIGH",
    "LEVEL_LOW",
    "RUN_BLOCK",
    "AchievabilityCheck",
    "AchievabilityReport",
    "Amplitude",
    "DoEPlan",
    "Level",
    "Orthogonality",
    "PlanRow",
    "achievability",
    "amplitude_from_prior",
    "orthogonality_of",
    "plackett_burman",
    "plan_runs",
    "plans_for_windows",
    "realized_matrix",
]


def _rotated(order: Sequence[str], seed: int) -> tuple[str, ...]:
    if not order:
        return ()
    offset = seed % len(order)
    return tuple(order[offset:]) + tuple(order[:offset])


def plackett_burman(
    window: Window,
    fund: ActiveFund,
    amplitude: Amplitude,
    seed: int,
) -> DoEPlan:
    injectors = tuple(sorted(fund.injectors))
    if not injectors:
        raise ValueError(
            f"no active injectors in the window {window.start}…{window.end}: "
            f"the plan width is a property of the window, not a constant"
        )
    runs = plan_runs(len(injectors))
    matrix = normalized(hadamard(runs))
    if not is_hadamard(matrix):
        raise ValueError(f"the built matrix of order {runs} is not orthogonal")
    assignment = _rotated(injectors, seed)
    rows: list[PlanRow] = []
    for run_index in range(1, runs):
        levels = {
            assignment[column - 1]: (
                Level.HIGH if matrix[run_index][column] == LEVEL_HIGH else Level.LOW
            )
            for column in range(1, len(assignment) + 1)
        }
        rows.append(PlanRow(run_index=run_index - 1, levels=levels))
    return DoEPlan(
        window=window,
        injectors=injectors,
        rows=tuple(rows),
        amplitude=amplitude,
        seed=seed,
    )


def plans_for_windows(
    sliced: Sequence[tuple[Window, ActiveFund]],
    amplitude: Amplitude,
    seed: int,
) -> tuple[DoEPlan, ...]:
    return tuple(
        plackett_burman(window, fund, amplitude, seed) for window, fund in sliced
    )
