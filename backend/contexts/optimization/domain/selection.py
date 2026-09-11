from __future__ import annotations

from backend.contexts.optimization.domain.search_limits import (
    MISSING_SIGMA,
)

from backend.contexts.optimization.domain.gates.opm_budget import (
    RunBudget,
)
from backend.contexts.optimization.domain.gates.incumbent import (
    IncumbentRecord,
)
from backend.contexts.optimization.domain.errors import (
    SearchRunError,
)
from dataclasses import (
    dataclass,
)
from typing import (
    Sequence,
)
from backend.core.contracts import (
    Schedule,
    Theta,
)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    schedule: Schedule
    theta: Theta
    predicted_npv: float
    schedule_hash: str
    provenance: dict[str, str]
    evaluations: int
    converged: bool
    self_consistent: bool
    static_violations: int | None = None
    dynamic_blocking_violations: int | None = None
    incumbent_history: tuple[IncumbentRecord, ...] = ()
    budget: RunBudget | None = None


def _risk_adjusted_npv(npv: float, sigma: float | None, beta: float) -> float:
    if beta <= 0.0:
        return float(npv)
    if sigma is None:
        raise SearchRunError(MISSING_SIGMA)
    return float(npv) - beta * float(sigma)


def select_finalist(finalists: Sequence[tuple], beta: float):
    if not finalists:
        raise SearchRunError(
            "отбор финалистов вызван на пустом наборе: выбирать не из чего"
        )
    if beta < 0.0:
        raise SearchRunError(
            f"коэффициент неприятия риска β={beta} отрицателен: штраф за "
            f"разброс не может быть премией"
        )
    if beta > 0.0 and any(item[7] is None for item in finalists):
        raise SearchRunError(MISSING_SIGMA)
    return max(
        finalists,
        key=lambda item: (
            item[3].self_consistent,
            _risk_adjusted_npv(item[0], item[7], beta),
        ),
    )


__all__ = [
    "SearchOutcome",
    "select_finalist",
]
