from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from contracts import Rule

IMPLEMENTED_RULES: tuple[Rule, ...] = (
    Rule.R0,
    Rule.R1,
    Rule.R2,
    Rule.R3,
    Rule.R4,
    Rule.R5,
    Rule.R6,
)

DEFAULT_RULE_FLAGS: Mapping[Rule, bool] = {
    Rule.R0: True,
    Rule.R1: True,
    Rule.R2: True,
    Rule.R3: True,
    Rule.R4: True,
    Rule.R5: True,
    Rule.R6: True,
    Rule.R7: False,
}


@dataclass(frozen=True, slots=True)
class RuleFlags:
    enabled: dict[Rule, bool] = field(
        default_factory=lambda: dict(DEFAULT_RULE_FLAGS)
    )

    def __post_init__(self) -> None:
        missing = set(Rule) - set(self.enabled)
        if missing:
            raise ValueError(
                f"флаги объявлены не для всех правил: {sorted(r.value for r in missing)}"
            )

    def is_on(self, rule: Rule) -> bool:
        return self.enabled[rule]

    def with_disabled(self, *rules: Rule) -> "RuleFlags":
        updated = dict(self.enabled)
        for rule in rules:
            updated[rule] = False
        return RuleFlags(enabled=updated)

    def with_enabled(self, *rules: Rule) -> "RuleFlags":
        updated = dict(self.enabled)
        for rule in rules:
            updated[rule] = True
        return RuleFlags(enabled=updated)


def all_off() -> RuleFlags:
    return RuleFlags(enabled={rule: False for rule in Rule})
