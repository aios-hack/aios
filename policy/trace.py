from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from contracts import ControlEvent, N_INTERVALS, Rule, TraceEntry, canonical_bytes

from policy.flags import RuleFlags
from policy.rules.base import RuleOutcome

TRACE_FORMAT = "trace-1"


@dataclass(frozen=True, slots=True)
class RunTrace:
    entries: tuple[TraceEntry, ...]
    flags: RuleFlags

    def __post_init__(self) -> None:
        for entry in self.entries:
            if not entry.inputs:
                raise ValueError(
                    f"{entry.rule.value}/{entry.well}: запись Trace без чисел входа"
                )
            if not (0 <= entry.control_step <= N_INTERVALS - 1):
                raise ValueError(
                    f"{entry.rule.value}/{entry.well}: control_step="
                    f"{entry.control_step} вне 0…{N_INTERVALS - 1}"
                )
            if not self.flags.is_on(entry.rule):
                raise ValueError(
                    f"{entry.rule.value} выключено флагом, но оставило запись "
                    f"по скважине {entry.well} на шаге {entry.control_step}"
                )

    def __len__(self) -> int:
        return len(self.entries)

    def by_rule(self, rule: Rule) -> tuple[TraceEntry, ...]:
        return tuple(e for e in self.entries if e.rule is rule)

    def by_well(self, well: str) -> tuple[TraceEntry, ...]:
        return tuple(e for e in self.entries if e.well == well)

    def by_step(self, control_step: int) -> tuple[TraceEntry, ...]:
        return tuple(e for e in self.entries if e.control_step == control_step)

    def at(self, control_step: int, well: str) -> tuple[TraceEntry, ...]:
        return tuple(
            e
            for e in self.entries
            if e.control_step == control_step and e.well == well
        )

    def select(
        self,
        rule: Rule | None = None,
        well: str | None = None,
        control_step: int | None = None,
    ) -> tuple[TraceEntry, ...]:
        selected = self.entries
        if rule is not None:
            selected = tuple(e for e in selected if e.rule is rule)
        if well is not None:
            selected = tuple(e for e in selected if e.well == well)
        if control_step is not None:
            selected = tuple(e for e in selected if e.control_step == control_step)
        return selected

    def rules_fired(self) -> tuple[Rule, ...]:
        seen: list[Rule] = []
        for entry in self.entries:
            if entry.rule not in seen:
                seen.append(entry.rule)
        return tuple(seen)

    def wells(self) -> tuple[str, ...]:
        return tuple(sorted({e.well for e in self.entries}))

    def steps(self) -> tuple[int, ...]:
        return tuple(sorted({e.control_step for e in self.entries}))

    def count_by_rule(self) -> dict[Rule, int]:
        counted: dict[Rule, int] = {rule: 0 for rule in Rule if self.flags.is_on(rule)}
        for entry in self.entries:
            counted[entry.rule] = counted.get(entry.rule, 0) + 1
        return counted

    def count_by_well_step(self) -> dict[tuple[str, int], int]:
        counted: dict[tuple[str, int], int] = {}
        for entry in self.entries:
            key = (entry.well, entry.control_step)
            counted[key] = counted.get(key, 0) + 1
        return counted

    def silent_rules(self) -> tuple[Rule, ...]:
        fired = set(self.rules_fired())
        return tuple(
            rule for rule in Rule if self.flags.is_on(rule) and rule not in fired
        )


@dataclass(frozen=True, slots=True)
class RunResultWithTrace:
    decisions: tuple[ControlEvent, ...]
    trace: RunTrace

    def __post_init__(self) -> None:
        traced = {(e.control_step, e.well) for e in self.trace.entries}
        untraced = [
            f"{event.well}@{event.control_step}"
            for event in self.decisions
            if (event.control_step, event.well) not in traced
        ]
        if untraced:
            raise ValueError(
                f"решения без записи Trace: {sorted(untraced)}"
            )


class TraceCollector:
    def __init__(self, flags: RuleFlags) -> None:
        self._flags = flags
        self._entries: list[TraceEntry] = []
        self._decisions: list[ControlEvent] = []

    def add(self, outcome: RuleOutcome) -> None:
        for entry in outcome.trace:
            if not self._flags.is_on(entry.rule):
                raise ValueError(
                    f"{entry.rule.value} выключено флагом, но вернуло запись Trace"
                )
        self._entries.extend(outcome.trace)
        self._decisions.extend(outcome.decisions)

    def finish(self) -> RunResultWithTrace:
        return RunResultWithTrace(
            decisions=tuple(self._decisions),
            trace=RunTrace(entries=tuple(self._entries), flags=self._flags),
        )


def collect(outcomes: Iterable[RuleOutcome], flags: RuleFlags) -> RunResultWithTrace:
    collector = TraceCollector(flags)
    for outcome in outcomes:
        collector.add(outcome)
    return collector.finish()


def run_trace(
    steps: Sequence[int],
    step_outcome: Callable[[int], RuleOutcome],
    flags: RuleFlags,
) -> RunResultWithTrace:
    collector = TraceCollector(flags)
    for control_step in steps:
        collector.add(step_outcome(control_step))
    return collector.finish()


def _entry_payload(entry: TraceEntry) -> dict[str, object]:
    return {
        "control_step": entry.control_step,
        "well": entry.well,
        "rule": entry.rule.value,
        "inputs": dict(sorted(entry.inputs.items())),
        "decision": entry.decision,
    }


def to_payload(trace: RunTrace) -> dict[str, object]:
    return {
        "format": TRACE_FORMAT,
        "flags": {
            rule.value: trace.flags.is_on(rule)
            for rule in sorted(Rule, key=lambda r: r.value)
        },
        "entries": [
            _entry_payload(entry)
            for entry in sorted(
                trace.entries,
                key=lambda e: (e.control_step, e.well, e.rule.value, e.decision),
            )
        ],
    }


def dumps(trace: RunTrace) -> str:
    return json.dumps(to_payload(trace), ensure_ascii=False, sort_keys=True)


def loads(text: str) -> RunTrace:
    payload = json.loads(text)
    if payload.get("format") != TRACE_FORMAT:
        raise ValueError(f"нераспознанный формат трассы: {payload.get('format')!r}")
    declared = payload.get("flags")
    if not isinstance(declared, dict):
        raise ValueError("в трассе нет блока флагов: отключение правил непроверяемо")
    flags = RuleFlags(enabled={rule: bool(declared[rule.value]) for rule in Rule})
    entries = tuple(
        TraceEntry(
            control_step=int(item["control_step"]),
            well=str(item["well"]),
            rule=Rule(item["rule"]),
            inputs={str(k): float(v) for k, v in dict(item["inputs"]).items()},
            decision=str(item["decision"]),
        )
        for item in payload["entries"]
    )
    return RunTrace(entries=entries, flags=flags)


def trace_hash(trace: RunTrace) -> str:
    return hashlib.sha256(canonical_bytes(to_payload(trace))).hexdigest()


def explain(trace: RunTrace, control_step: int, well: str) -> tuple[str, ...]:
    lines: list[str] = []
    for entry in trace.at(control_step, well):
        numbers = ", ".join(
            f"{name}={value:g}" for name, value in sorted(entry.inputs.items())
        )
        lines.append(f"{entry.rule.value} → {entry.decision}: {numbers}")
    return tuple(lines)


def ablation_delta(
    baseline: Mapping[Rule, int], ablated: Mapping[Rule, int], rule: Rule
) -> int:
    return baseline.get(rule, 0) - ablated.get(rule, 0)
