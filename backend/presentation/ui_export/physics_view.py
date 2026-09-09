from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.ml.surrogate.physics_checks import Invariant, Severity, severity_of

__all__ = [
    "PHYSICS_INVARIANTS",
    "PHYSICS_TOTAL",
    "ScenarioPhysics",
    "physics_json",
]

PHYSICS_INVARIANTS: tuple[str, ...] = tuple(item.value for item in Invariant)

PHYSICS_TOTAL: int = len(PHYSICS_INVARIANTS)


@dataclass(frozen=True, slots=True)
class ScenarioPhysics:
    evaluated: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()
    blocking_count: int = 0
    warning_count: int = 0

    def __post_init__(self) -> None:
        known = set(PHYSICS_INVARIANTS)
        seen: set[str] = set()
        for name in self.evaluated:
            if name not in known:
                raise ValueError(f"неизвестный инвариант в evaluated: {name!r}")
            if name in seen:
                raise ValueError(f"инвариант {name!r} повторён в evaluated")
            seen.add(name)
        for name, reason in self.skipped:
            if name not in known:
                raise ValueError(f"неизвестный инвариант в skipped: {name!r}")
            if name in seen:
                raise ValueError(
                    f"инвариант {name!r} одновременно посчитан и пропущен"
                )
            if not reason:
                raise ValueError(f"инвариант {name!r} пропущен без причины")
            seen.add(name)
        if self.blocking_count < 0 or self.warning_count < 0:
            raise ValueError("счётчики флагов физпроверок не могут быть отрицательными")

    @classmethod
    def from_report(cls, report: Any) -> "ScenarioPhysics":
        document = report.as_dict() if hasattr(report, "as_dict") else report
        return cls.from_dict(document)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "ScenarioPhysics":
        evaluated = tuple(str(name) for name in document.get("evaluated", ()))
        skipped_source = document.get("skipped", {}) or {}
        skipped = tuple(
            (str(name), str(reason))
            for name, reason in sorted(dict(skipped_source).items())
        )
        counts = dict(document.get("counts", {}) or {})
        blocking = document.get("blocking_count")
        warning = document.get("warning_count")
        if blocking is None or warning is None:
            blocking = sum(
                int(value)
                for name, value in counts.items()
                if severity_of(str(name)) is Severity.BLOCKING
            )
            warning = sum(int(value) for value in counts.values()) - blocking
        return cls(
            evaluated=evaluated,
            skipped=skipped,
            blocking_count=int(blocking),
            warning_count=int(warning),
        )

    @property
    def complete(self) -> bool:
        return len(self.evaluated) == PHYSICS_TOTAL

    @property
    def admissible(self) -> bool:
        return self.complete and self.blocking_count == 0


def physics_json(physics: ScenarioPhysics | None) -> dict[str, Any] | None:
    if physics is None:
        return None
    return {
        "total": PHYSICS_TOTAL,
        "evaluated_count": len(physics.evaluated),
        "evaluated": sorted(physics.evaluated),
        "skipped": [
            {
                "invariant": name,
                "reason": reason,
                "severity": severity_of(name).value,
            }
            for name, reason in physics.skipped
        ],
        "blocking_count": physics.blocking_count,
        "warning_count": physics.warning_count,
        "complete": physics.complete,
        "admissible": physics.admissible,
        "warning_invariants": [
            name
            for name in PHYSICS_INVARIANTS
            if severity_of(name) is Severity.WARNING
        ],
    }
