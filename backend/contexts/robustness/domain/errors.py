from __future__ import annotations

from backend.shared.errors import (
    DomainError,
)


class OodError(DomainError):
    default_code = "robustness.ood"


class ScenarioDensityError(DomainError):
    default_code = "robustness.scenario_density"


__all__ = [
    "OodError",
    "ScenarioDensityError",
]
