from __future__ import annotations

from typing import Any, Mapping


class AiosError(Exception):
    default_code: str = "aios.error"

    code: str
    message: str
    details: Mapping[str, Any]

    def __init__(self, message: str, *, code: str | None = None, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or type(self).default_code
        self.details = dict(details)

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "details": dict(self.details)}

    def __str__(self) -> str:
        return self.message


class DomainError(AiosError, ValueError):
    default_code = "domain.error"


class ValidationError(DomainError):
    default_code = "validation.error"


class NotFoundError(AiosError, LookupError):
    default_code = "not_found"


class ConflictError(AiosError, RuntimeError):
    default_code = "conflict"


class ConfigurationError(AiosError, RuntimeError):
    default_code = "configuration.error"


class InfrastructureError(AiosError, RuntimeError):
    default_code = "infrastructure.error"


class ExternalServiceError(InfrastructureError):
    default_code = "external_service.error"


class UnavailableError(AiosError, RuntimeError):
    default_code = "unavailable"


__all__ = [
    "AiosError",
    "ConfigurationError",
    "ConflictError",
    "DomainError",
    "ExternalServiceError",
    "InfrastructureError",
    "NotFoundError",
    "UnavailableError",
    "ValidationError",
]
