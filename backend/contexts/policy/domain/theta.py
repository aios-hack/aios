from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from backend.core.contracts import Rule, Theta
from backend.contexts.policy.domain.policy import MAX_THETA_PARAMS

THETA_CAP = MAX_THETA_PARAMS


@dataclass(frozen=True, slots=True)
class ThetaSpec:
    name: str
    rule: Rule
    low: float
    high: float
    default: float

    def __post_init__(self) -> None:
        if self.low >= self.high:
            raise ValueError(f"{self.name}: пустые границы [{self.low}, {self.high}]")
        if not (self.low <= self.default <= self.high):
            raise ValueError(f"{self.name}: умолчание {self.default} вне границ")


R0_SPECS: tuple[ThetaSpec, ...] = ()

R1_SPECS: tuple[ThetaSpec, ...] = (
    ThetaSpec("r1_lag_months", Rule.R1, 0.0, 12.0, 3.0),
)

R2_SPECS: tuple[ThetaSpec, ...] = (
    ThetaSpec("r2_watercut_pivot", Rule.R2, 0.5, 0.99, 0.9),
    ThetaSpec("r2_gain", Rule.R2, 0.0, 1.0, 0.3),
)

R3_SPECS: tuple[ThetaSpec, ...] = (
    ThetaSpec("r3_months_in_loss", Rule.R3, 1.0, 12.0, 3.0),
    ThetaSpec("r3_reopen_margin", Rule.R3, 0.0, 1.0, 0.2),
)

R4_SPECS: tuple[ThetaSpec, ...] = ()

R5_SPECS: tuple[ThetaSpec, ...] = (
    ThetaSpec("r5_compensation_low", Rule.R5, 0.5, 1.0, 0.9),
    ThetaSpec("r5_compensation_high", Rule.R5, 1.0, 1.6, 1.15),
)

R6_SPECS: tuple[ThetaSpec, ...] = (
    ThetaSpec("r6_payback_years", Rule.R6, 1.0, 15.0, 5.0),
)

RESERVED_FOR_R7 = 0

R7_SPECS: tuple[ThetaSpec, ...] = (
    ThetaSpec("r7_cycle_months", Rule.R7, 1.0, 12.0, 3.0),
    ThetaSpec("r7_watercut_floor", Rule.R7, 0.8, 0.99, 0.95),
)

SPECS: tuple[ThetaSpec, ...] = (
    R0_SPECS
    + R1_SPECS
    + R2_SPECS
    + R3_SPECS
    + R4_SPECS
    + R5_SPECS
    + R6_SPECS
    + R7_SPECS
)

SPEC_BY_NAME: Mapping[str, ThetaSpec] = {spec.name: spec for spec in SPECS}


def specs_for(rule: Rule) -> tuple[ThetaSpec, ...]:
    return tuple(spec for spec in SPECS if spec.rule is rule)


def declared_bounds() -> dict[str, tuple[float, float]]:
    return {spec.name: (spec.low, spec.high) for spec in SPECS}


def default_theta() -> Theta:
    return Theta(
        values={spec.name: spec.default for spec in SPECS},
        bounds=declared_bounds(),
    )


def make_theta(values: Mapping[str, float]) -> Theta:
    unknown = set(values) - set(SPEC_BY_NAME)
    if unknown:
        raise ValueError(f"незаявленные параметры θ: {sorted(unknown)}")
    merged = {spec.name: spec.default for spec in SPECS}
    merged.update(values)
    for name, value in merged.items():
        spec = SPEC_BY_NAME[name]
        if not (spec.low <= value <= spec.high):
            raise ValueError(
                f"{name}={value} вне объявленных границ [{spec.low}, {spec.high}]"
            )
    return Theta(values=merged, bounds=declared_bounds())


def read(theta: Theta, name: str) -> float:
    if name not in SPEC_BY_NAME:
        raise ValueError(f"{name} не объявлен в реестре θ")
    if name not in theta.values:
        raise ValueError(f"{name} отсутствует в поданном θ")
    low, high = SPEC_BY_NAME[name].low, SPEC_BY_NAME[name].high
    value = theta.values[name]
    if not (low <= value <= high):
        raise ValueError(f"{name}={value} вне границ [{low}, {high}]")
    return value


def total_budget_ok() -> bool:
    return len(SPECS) <= THETA_CAP


def budget_by_rule() -> dict[Rule, int]:
    return {rule: len(specs_for(rule)) for rule in Rule}


def budget_used() -> int:
    return len(SPECS)


def budget_free() -> int:
    return THETA_CAP - len(SPECS)


@dataclass(frozen=True, slots=True)
class ThetaRegistry:
    specs: tuple[ThetaSpec, ...]
    cap: int = THETA_CAP

    def __post_init__(self) -> None:
        if self.cap <= 0:
            raise ValueError(
                f"потолок θ равен {self.cap}: искать нечего, размерность "
                f"пространства поиска не положительна"
            )
        names = [spec.name for spec in self.specs]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            raise ValueError(f"параметр θ объявлен дважды: {duplicated}")
        if len(self.specs) > self.cap:
            raise ValueError(
                f"θ: {len(self.specs)} параметров > {self.cap} — CMA-ES "
                f"строит ковариацию размера {len(self.specs)}², и цена оценки "
                f"растёт быстрее, чем бюджет прогонов; выбор, что выкинуть, "
                f"принимается явно, а не молча"
            )

    def by_name(self) -> Mapping[str, ThetaSpec]:
        return {spec.name: spec for spec in self.specs}

    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.specs)

    def used(self) -> int:
        return len(self.specs)

    def free(self) -> int:
        return self.cap - len(self.specs)

    def for_rule(self, rule: Rule) -> tuple[ThetaSpec, ...]:
        return tuple(spec for spec in self.specs if spec.rule is rule)

    def bounds(self) -> dict[str, tuple[float, float]]:
        return {spec.name: (spec.low, spec.high) for spec in self.specs}

    def defaults(self) -> Theta:
        return Theta(
            values={spec.name: spec.default for spec in self.specs},
            bounds=self.bounds(),
        )

    def without(self, *names: str) -> "ThetaRegistry":
        unknown = sorted(set(names) - set(self.names()))
        if unknown:
            raise ValueError(f"незаявленные параметры θ: {unknown}")
        dropped = set(names)
        return ThetaRegistry(
            specs=tuple(
                spec for spec in self.specs if spec.name not in dropped
            ),
            cap=self.cap,
        )

    def extended_with(self, added: Iterable[ThetaSpec]) -> "ThetaRegistry":
        return ThetaRegistry(specs=self.specs + tuple(added), cap=self.cap)


DEFAULT_THETA_REGISTRY = ThetaRegistry(specs=SPECS)
