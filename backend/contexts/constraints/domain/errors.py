from __future__ import annotations

from backend.shared.errors import (
    ValidationError,
)


class CaseError(ValidationError):
    default_code = "constraints.case"


class ConfigError(ValidationError):
    default_code = "constraints.config"


__all__ = [
    "CaseError",
    "ConfigError",
]
