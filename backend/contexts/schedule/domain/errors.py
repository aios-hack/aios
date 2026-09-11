from __future__ import annotations

from backend.shared.errors import (
    DomainError,
    ValidationError,
)


class ScheduleParseError(ValidationError):
    default_code = "schedule.parse"


class ScheduleBuildError(ValidationError):
    default_code = "schedule.build"


class ScheduleCanonicalError(ValidationError):
    default_code = "schedule.canonical"


class ScheduleEmitError(ValidationError):
    default_code = "schedule.emit"


class ReplayError(ValidationError):
    default_code = "schedule.replay"


class CaseLimitsError(DomainError):
    default_code = "schedule.case_limits"


__all__ = [
    "CaseLimitsError",
    "ReplayError",
    "ScheduleBuildError",
    "ScheduleCanonicalError",
    "ScheduleEmitError",
    "ScheduleParseError",
]
