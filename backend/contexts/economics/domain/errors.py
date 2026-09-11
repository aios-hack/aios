from __future__ import annotations

from backend.shared.errors import (
    DomainError,
    UnavailableError,
    ValidationError,
)


class EconomicsError(DomainError):
    default_code = "economics.npv"


class LedgerError(DomainError):
    default_code = "economics.ledger"


class DecompositionError(DomainError):
    default_code = "economics.decomposition"


class NormativesError(ValidationError):
    default_code = "economics.normatives"


class BaseCaseError(DomainError):
    default_code = "economics.base_case"


class ParityError(DomainError):
    default_code = "economics.parity"


class ReferenceUnavailableError(UnavailableError):
    default_code = "economics.reference_unavailable"


__all__ = [
    "BaseCaseError",
    "DecompositionError",
    "EconomicsError",
    "LedgerError",
    "NormativesError",
    "ParityError",
    "ReferenceUnavailableError",
]
