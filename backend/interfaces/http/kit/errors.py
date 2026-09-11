from __future__ import annotations

import logging
from typing import Any

from backend.shared.errors import (
    AiosError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    InfrastructureError,
    NotFoundError,
    UnavailableError,
    ValidationError,
)

logger = logging.getLogger(__name__)

INTERNAL_CODE = "internal"
INTERNAL_MESSAGE = "Internal service error"

_STATUS_CODES: tuple[tuple[type[AiosError], int], ...] = (
    (ValidationError, 400),
    (NotFoundError, 404),
    (ConflictError, 409),
    (ExternalServiceError, 502),
    (UnavailableError, 503),
    (ConfigurationError, 503),
    (InfrastructureError, 500),
)


def status_for(error: AiosError) -> int:
    for kind, status in _STATUS_CODES:
        if isinstance(error, kind):
            return status
    return 500


def body_for(error: AiosError) -> dict[str, Any]:
    return error.as_dict()


def internal_body() -> dict[str, Any]:
    return {"error": INTERNAL_CODE, "message": INTERNAL_MESSAGE, "details": {}}


def to_response(error: BaseException) -> tuple[int, dict[str, Any]]:
    if isinstance(error, AiosError):
        return status_for(error), body_for(error)
    logger.exception("unhandled error while serving a request", exc_info=error)
    return 500, internal_body()


__all__ = [
    "INTERNAL_CODE",
    "INTERNAL_MESSAGE",
    "body_for",
    "internal_body",
    "status_for",
    "to_response",
]
