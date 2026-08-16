from __future__ import annotations

from typing import Callable

from contracts import Rule, Theta

from policy.flags import IMPLEMENTED_RULES, RuleFlags
from policy.rules import r0, r1, r2, r3, r4, r5, r6
from policy.rules.base import EMPTY_OUTCOME, PolicyRule, RuleOutcome, merge
from policy.state import PolicyState, RuleContext

RuleFn = Callable[[PolicyState, RuleContext, Theta], RuleOutcome]

RULE_FUNCTIONS: dict[Rule, RuleFn] = {
    Rule.R0: r0.apply,
    Rule.R1: r1.apply,
    Rule.R2: r2.apply,
    Rule.R3: r3.apply,
    Rule.R4: r4.apply,
    Rule.R5: r5.apply,
    Rule.R6: r6.apply,
}

ADMISSION_CRITERIA: dict[Rule, str] = {
    Rule.R0: r0.ADMISSION_CRITERION,
    Rule.R1: r1.ADMISSION_CRITERION,
    Rule.R2: r2.ADMISSION_CRITERION,
    Rule.R3: r3.ADMISSION_CRITERION,
    Rule.R4: r4.ADMISSION_CRITERION,
    Rule.R5: r5.ADMISSION_CRITERION,
    Rule.R6: r6.ADMISSION_CRITERION,
}

THETA_NAMES_BY_RULE: dict[Rule, tuple[str, ...]] = {
    Rule.R0: r0.THETA_NAMES,
    Rule.R1: r1.THETA_NAMES,
    Rule.R2: r2.THETA_NAMES,
    Rule.R3: r3.THETA_NAMES,
    Rule.R4: r4.THETA_NAMES,
    Rule.R5: r5.THETA_NAMES,
    Rule.R6: r6.THETA_NAMES,
}


SUPERSEDED_WHEN_ON: dict[Rule, tuple[Rule, ...]] = {
    Rule.R3: (Rule.R0,),
}


def superseded(flags: RuleFlags) -> frozenset[Rule]:
    blocked: set[Rule] = set()
    for gate, covered in SUPERSEDED_WHEN_ON.items():
        if flags.is_on(gate):
            blocked.update(covered)
    return frozenset(blocked)


def apply_rule(
    rule: Rule,
    state: PolicyState,
    context: RuleContext,
    theta: Theta,
    flags: RuleFlags,
) -> RuleOutcome:
    if rule not in RULE_FUNCTIONS:
        raise NotImplementedError(f"{rule.value} в этой задаче не реализовано")
    if not flags.is_on(rule):
        return EMPTY_OUTCOME
    return RULE_FUNCTIONS[rule](state, context, theta)


def apply_all(
    state: PolicyState,
    context: RuleContext,
    theta: Theta,
    flags: RuleFlags,
) -> RuleOutcome:
    blocked = superseded(flags)
    return merge(
        [
            apply_rule(rule, state, context, theta, flags)
            for rule in IMPLEMENTED_RULES
            if rule not in blocked
        ]
    )


__all__ = [
    "ADMISSION_CRITERIA",
    "EMPTY_OUTCOME",
    "PolicyRule",
    "RULE_FUNCTIONS",
    "RuleFn",
    "RuleOutcome",
    "SUPERSEDED_WHEN_ON",
    "THETA_NAMES_BY_RULE",
    "apply_all",
    "apply_rule",
    "merge",
    "superseded",
    "r0",
    "r1",
    "r2",
    "r3",
    "r4",
    "r5",
    "r6",
]
