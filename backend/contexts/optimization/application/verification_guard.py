from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.optimization.domain.errors import VerificationGuardError


BASE_NPV = 11_873_122_324.91
OIL_DENSITY_T_PER_M3 = 0.9131


@dataclass(frozen=True, slots=True)
class GuardCheck:
    name: str
    expected: str | None
    actual: str
    source: str

    @property
    def checked(self) -> bool:
        return self.expected is not None

    @property
    def holds(self) -> bool:
        return self.expected is not None and self.expected == self.actual

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "checked": self.checked,
            "holds": self.holds,
            "expected": self.expected,
            "actual": self.actual,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class GuardReport:
    schedule: GuardCheck
    constraints: GuardCheck

    @property
    def checks(self) -> tuple[GuardCheck, ...]:
        return (self.schedule, self.constraints)

    @property
    def unchecked(self) -> tuple[GuardCheck, ...]:
        return tuple(check for check in self.checks if not check.checked)

    @property
    def fully_checked(self) -> bool:
        return not self.unchecked

    def as_dict(self) -> dict[str, object]:
        return {
            "fully_checked": self.fully_checked,
            "unchecked": [check.name for check in self.unchecked],
            "checks": [check.as_dict() for check in self.checks],
        }

    def raise_if_broken(self) -> None:
        broken = [
            check for check in self.checks if check.checked and not check.holds
        ]
        if not broken:
            return
        details = "; ".join(
            f"{check.name}: in the run {check.expected}, presented "
            f"{check.actual} (reference source: {check.source})"
            for check in broken
        )
        raise VerificationGuardError(
            "verification abandoned before starting Flow: what was presented for "
            f"checking diverges from what the run recorded — {details}"
        )
