from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from backend.core.contracts import ControlEvent, Rule, Theta, TraceEntry

from backend.domain.policy.state import PolicyState, RuleContext


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    decisions: tuple[ControlEvent, ...]
    trace: tuple[TraceEntry, ...]

    def __post_init__(self) -> None:
        for entry in self.trace:
            if not entry.inputs:
                raise ValueError(
                    f"{entry.rule.value}/{entry.well}: запись Trace без чисел входа"
                )


EMPTY_OUTCOME = RuleOutcome(decisions=(), trace=())


class PolicyRule(Protocol):
    rule: Rule
    admission_criterion: str
    theta_names: tuple[str, ...]

    def __call__(
        self, state: PolicyState, context: RuleContext, theta: Theta
    ) -> RuleOutcome: ...


def merge(outcomes: Sequence[RuleOutcome]) -> RuleOutcome:
    decisions: list[ControlEvent] = []
    trace: list[TraceEntry] = []
    for outcome in outcomes:
        decisions.extend(outcome.decisions)
        trace.extend(outcome.trace)
    return RuleOutcome(decisions=tuple(decisions), trace=tuple(trace))
