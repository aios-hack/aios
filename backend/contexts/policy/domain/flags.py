from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from backend.contexts.policy.domain.policy import Rule

IMPLEMENTED_RULES: tuple[Rule, ...] = (
    Rule.R0,
    Rule.R1,
    Rule.R2,
    Rule.R3,
    Rule.R4,
    Rule.R5,
    Rule.R6,
    Rule.R7,
)

WATERCUT_CAP_FEATURE = "r0_watercut_cap"

WATERCUT_CAP_UNMEASURED = (
    "Shut-in by the watercut ceiling showed no NPV gain in the measurement: "
    "the flag is off by default and is switched on only by an explicit opt-in."
)

DEFAULT_FEATURE_FLAGS: Mapping[str, bool] = {
    WATERCUT_CAP_FEATURE: False,
}

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
    features: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_FEATURE_FLAGS)
    )

    def __post_init__(self) -> None:
        missing = set(Rule) - set(self.enabled)
        if missing:
            raise ValueError(
                f"flags are not declared for every rule: {sorted(r.value for r in missing)}"
            )
        unknown = set(self.features) - set(DEFAULT_FEATURE_FLAGS)
        if unknown:
            raise ValueError(
                f"unknown flags: {sorted(unknown)}"
            )

    def is_on(self, rule: Rule) -> bool:
        return self.enabled[rule]

    def feature_on(self, name: str) -> bool:
        if name not in DEFAULT_FEATURE_FLAGS:
            raise ValueError(f"unknown flag {name!r}")
        return self.features.get(name, DEFAULT_FEATURE_FLAGS[name])

    def with_disabled(self, *rules: Rule) -> "RuleFlags":
        updated = dict(self.enabled)
        for rule in rules:
            updated[rule] = False
        return RuleFlags(enabled=updated, features=dict(self.features))

    def with_enabled(self, *rules: Rule) -> "RuleFlags":
        updated = dict(self.enabled)
        for rule in rules:
            updated[rule] = True
        return RuleFlags(enabled=updated, features=dict(self.features))

    def with_feature(self, name: str, on: bool) -> "RuleFlags":
        if name not in DEFAULT_FEATURE_FLAGS:
            raise ValueError(f"unknown flag {name!r}")
        updated = dict(self.features)
        updated[name] = on
        return RuleFlags(enabled=dict(self.enabled), features=updated)


def all_off() -> RuleFlags:
    return RuleFlags(
        enabled={rule: False for rule in Rule},
        features={name: False for name in DEFAULT_FEATURE_FLAGS},
    )
