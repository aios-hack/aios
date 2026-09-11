from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.connectivity.domain.connectivity import Groups, Lambda
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.economics.domain.economics import NpvTable
from backend.contexts.policy.domain.policy import TraceEntry
from backend.contexts.reservoir.domain.response import IntervalResponse, StateAtDate
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.runs.domain.run_result import FinalNpvArtifact


@dataclass(frozen=True, slots=True)
class RunArtifact:

    config_hash: str
    schedule: Schedule
    state_at_date: tuple[StateAtDate, ...]
    interval_response: tuple[IntervalResponse, ...]
    npv_table: NpvTable
    trace: tuple[TraceEntry, ...]
    groups: Groups
    lambda_: Lambda
    constraints: Constraints
    converged: bool
    self_consistent: bool
    final_npv: FinalNpvArtifact | None = None
