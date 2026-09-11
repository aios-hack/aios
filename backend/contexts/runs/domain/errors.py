from __future__ import annotations

from backend.shared.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class SubmissionError(DomainError):
    default_code = "runs.submission"


class RunRequestError(ValidationError):
    default_code = "runs.request"


class RunNotFoundError(NotFoundError):
    default_code = "runs.not_found"


class RunBusyError(ConflictError):
    default_code = "runs.busy"


__all__ = [
    "RunBusyError",
    "RunNotFoundError",
    "RunRequestError",
    "SubmissionError",
]
