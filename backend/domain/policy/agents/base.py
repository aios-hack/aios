from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol, runtime_checkable

from backend.core.contracts import ControlEvent, EventKind, Rule, TraceEntry

from backend.domain.policy.levels import Level, LeveledTraceEntry
from backend.domain.policy.state import PolicyState, RuleContext

DEFAULT_RANK = 0
BOUND_TOLERANCE_M3_PER_DAY = 1e-9


class Verdict(Enum):
    ALLOW = "ALLOW"
    VETO = "VETO"


class BoundSense(Enum):
    CEILING = "CEILING"
    FLOOR = "FLOOR"


@dataclass(frozen=True, slots=True)
class Bound:
    well: str
    kind: EventKind
    sense: BoundSense
    value: float

    def __post_init__(self) -> None:
        if not self.well:
            raise ValueError("ограничение без имени скважины: адресата нет")
        if self.value < 0.0:
            raise ValueError(
                f"{self.well}/{self.kind.value}: отрицательная граница "
                f"{self.value} — ограничение не интерпретируемо"
            )

    def key(self) -> tuple[str, str, str]:
        return (self.well, self.kind.value, self.sense.value)

    def tightened_by(self, other: Bound) -> Bound:
        if self.key() != other.key():
            raise ValueError(
                f"нельзя сравнить границы разных величин: {self.key()} и "
                f"{other.key()}"
            )
        if self.sense is BoundSense.CEILING:
            return self if self.value <= other.value else other
        return self if self.value >= other.value else other

    def allows(self, value: float) -> bool:
        if self.sense is BoundSense.CEILING:
            return value <= self.value + BOUND_TOLERANCE_M3_PER_DAY
        return value >= self.value - BOUND_TOLERANCE_M3_PER_DAY

    def clamp(self, value: float) -> float:
        if self.sense is BoundSense.CEILING:
            return min(value, self.value)
        return max(value, self.value)


@dataclass(frozen=True, slots=True)
class Proposal:
    level: Level
    agent: str
    decisions: tuple[ControlEvent, ...]
    rule_by_decision: tuple[Rule, ...]
    trace: tuple[LeveledTraceEntry, ...]
    verdict: Verdict = Verdict.ALLOW
    bounds: tuple[Bound, ...] = ()
    veto_reason: str = ""

    def __post_init__(self) -> None:
        if not self.agent:
            raise ValueError("предложение без имени агента: автора не восстановить")
        if len(self.decisions) != len(self.rule_by_decision):
            raise ValueError(
                f"{self.agent}: {len(self.decisions)} решений при "
                f"{len(self.rule_by_decision)} правилах — авторство решения "
                f"не восстановимо"
            )
        for leveled in self.trace:
            if leveled.level is not self.level:
                raise ValueError(
                    f"{self.agent}: запись уровня {leveled.level.value} в "
                    f"предложении уровня {self.level.value}"
                )
        if self.verdict is Verdict.VETO:
            if self.decisions:
                raise ValueError(
                    f"{self.agent}: вето с {len(self.decisions)} решениями — "
                    f"запрет и уставка одновременно не исполнимы"
                )
            if not self.veto_reason:
                raise ValueError(
                    f"{self.agent}: вето без причины — на защите его нечем "
                    f"объяснить"
                )
        elif self.veto_reason:
            raise ValueError(
                f"{self.agent}: причина вето при вердикте "
                f"{self.verdict.value}: решение и объяснение расходятся"
            )
        seen: set[tuple[str, str, str]] = set()
        for bound in self.bounds:
            if bound.key() in seen:
                raise ValueError(
                    f"{self.agent}: граница {bound.key()} объявлена дважды — "
                    f"какая из них действует, не определено"
                )
            seen.add(bound.key())

    def bound_for(
        self, well: str, kind: EventKind, sense: BoundSense
    ) -> Bound | None:
        key = (well, kind.value, sense.value)
        for bound in self.bounds:
            if bound.key() == key:
                return bound
        return None


def merge_bounds(
    earlier: tuple[Bound, ...], later: tuple[Bound, ...]
) -> tuple[tuple[Bound, ...], tuple[tuple[Bound, Bound], ...]]:
    merged: dict[tuple[str, str, str], Bound] = {
        bound.key(): bound for bound in earlier
    }
    tightened: list[tuple[Bound, Bound]] = []
    for bound in later:
        standing = merged.get(bound.key())
        if standing is None:
            merged[bound.key()] = bound
            continue
        winner = standing.tightened_by(bound)
        if winner is not standing:
            tightened.append((standing, winner))
        merged[bound.key()] = winner
    ordered = tuple(merged[key] for key in sorted(merged))
    return ordered, tuple(tightened)


def _clamped(event: ControlEvent, bounds: tuple[Bound, ...]) -> ControlEvent:
    if event.value is None:
        return event
    value = event.value
    for bound in bounds:
        if bound.well != event.well or bound.kind is not event.kind:
            continue
        value = bound.clamp(value)
    if value == event.value:
        return event
    return replace(event, value=value)


def _restriction_entry(
    level: Level,
    agent: str,
    control_step: int,
    rule: Rule,
    standing: Bound,
    winner: Bound,
    restricted_by: str,
) -> LeveledTraceEntry:
    return LeveledTraceEntry(
        level=level,
        agent=agent,
        entry=TraceEntry(
            control_step=control_step,
            well=standing.well,
            rule=rule,
            inputs={
                "standing_bound_m3_per_day": standing.value,
                "proposed_bound_m3_per_day": winner.value,
                "applied_bound_m3_per_day": winner.value,
            },
            decision=(
                f"RESTRICTED_{standing.sense.value}_{standing.kind.value}"
                f"_BY_{restricted_by}"
            ),
        ),
    )


def _veto_entry(
    level: Level, agent: str, control_step: int, rule: Rule, reason: str
) -> LeveledTraceEntry:
    return LeveledTraceEntry(
        level=level,
        agent=agent,
        entry=TraceEntry(
            control_step=control_step,
            well=agent,
            rule=rule,
            inputs={"vetoed_decisions": 0.0},
            decision=f"VETO_{reason}",
        ),
    )


def merge_proposals(
    proposals: tuple[Proposal, ...], control_step: int, rule: Rule = Rule.R0
) -> Proposal:
    if not proposals:
        raise ValueError(
            "слияние пустого списка предложений: результат шага не определён"
        )
    head = proposals[0]
    for proposal in proposals:
        if proposal.level is not head.level:
            raise ValueError(
                f"слияние предложений разных уровней: {head.level.value} и "
                f"{proposal.level.value}"
            )
    if len(proposals) == 1:
        if head.verdict is Verdict.ALLOW and head.bounds and head.decisions:
            return replace(
                head,
                decisions=tuple(
                    _clamped(event, head.bounds) for event in head.decisions
                ),
            )
        return head

    agent = head.agent
    verdict = head.verdict
    veto_reason = head.veto_reason
    bounds = head.bounds
    decisions = list(head.decisions)
    rules = list(head.rule_by_decision)
    trace = list(head.trace)

    for proposal in proposals[1:]:
        merged, tightened = merge_bounds(bounds, proposal.bounds)
        for standing, winner in tightened:
            trace.append(
                _restriction_entry(
                    head.level,
                    agent,
                    control_step,
                    rule,
                    standing,
                    winner,
                    proposal.agent,
                )
            )
        bounds = merged
        trace.extend(proposal.trace)
        if verdict is Verdict.VETO:
            continue
        if proposal.verdict is Verdict.VETO:
            verdict = Verdict.VETO
            veto_reason = proposal.veto_reason
            decisions = []
            rules = []
            trace.append(
                _veto_entry(
                    head.level, agent, control_step, rule, proposal.veto_reason
                )
            )
            continue
        decisions.extend(proposal.decisions)
        rules.extend(proposal.rule_by_decision)

    if verdict is Verdict.ALLOW and bounds:
        decisions = [_clamped(event, bounds) for event in decisions]

    return Proposal(
        level=head.level,
        agent=agent,
        decisions=tuple(decisions),
        rule_by_decision=tuple(rules),
        trace=tuple(trace),
        verdict=verdict,
        bounds=bounds,
        veto_reason=veto_reason,
    )


@runtime_checkable
class Agent(Protocol):
    name: str
    level: Level
    responsibilities: tuple[str, ...]

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal: ...


@runtime_checkable
class RankedAgent(Agent, Protocol):
    rank: int
