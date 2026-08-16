from __future__ import annotations

from typing import Callable

from contracts import Rule, Theta

from policy.flags import IMPLEMENTED_RULES, RuleFlags
from policy.rules import r0, r1, r2
from policy.rules.base import EMPTY_OUTCOME, PolicyRule, RuleOutcome, merge
from policy.state import PolicyState, RuleContext

RuleFn = Callable[[PolicyState, RuleContext, Theta], RuleOutcome]

RULE_FUNCTIONS: dict[Rule, RuleFn] = {
    Rule.R0: r0.apply,
    Rule.R1: r1.apply,
    Rule.R2: r2.apply,
}

ADMISSION_CRITERIA: dict[Rule, str] = {
    Rule.R0: r0.ADMISSION_CRITERION,
    Rule.R1: r1.ADMISSION_CRITERION,
    Rule.R2: r2.ADMISSION_CRITERION,
}

THETA_NAMES_BY_RULE: dict[Rule, tuple[str, ...]] = {
    Rule.R0: r0.THETA_NAMES,
    Rule.R1: r1.THETA_NAMES,
    Rule.R2: r2.THETA_NAMES,
}


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
    return merge(
        [
            apply_rule(rule, state, context, theta, flags)
            for rule in IMPLEMENTED_RULES
        ]
    )


__all__ = [
    "ADMISSION_CRITERIA",
    "EMPTY_OUTCOME",
    "PolicyRule",
    "RULE_FUNCTIONS",
    "RuleFn",
    "RuleOutcome",
    "THETA_NAMES_BY_RULE",
    "apply_all",
    "apply_rule",
    "merge",
    "r0",
    "r1",
    "r2",
]
