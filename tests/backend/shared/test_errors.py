from __future__ import annotations

import pytest

from backend.shared.errors import (
    AiosError,
    ConfigurationError,
    ConflictError,
    DomainError,
    ExternalServiceError,
    InfrastructureError,
    NotFoundError,
    UnavailableError,
    ValidationError,
)

FAMILY = (
    DomainError,
    ValidationError,
    NotFoundError,
    ConflictError,
    ConfigurationError,
    InfrastructureError,
    ExternalServiceError,
    UnavailableError,
)


@pytest.mark.parametrize("kind", FAMILY)
def test_every_error_descends_from_the_root(kind: type[AiosError]) -> None:
    assert issubclass(kind, AiosError)


@pytest.mark.parametrize("kind", FAMILY)
def test_every_error_carries_a_default_code(kind: type[AiosError]) -> None:
    assert kind.default_code
    assert kind("боль").code == kind.default_code


def test_validation_is_a_domain_error_and_external_is_infrastructure() -> None:
    assert issubclass(ValidationError, DomainError)
    assert issubclass(ExternalServiceError, InfrastructureError)


def test_explicit_code_wins_over_the_default() -> None:
    error = ValidationError("кейс отклонён", code="runs.case_rejected", path="case.json")

    assert error.code == "runs.case_rejected"
    assert error.message == "кейс отклонён"
    assert error.details == {"path": "case.json"}


def test_as_dict_is_the_wire_shape() -> None:
    error = NotFoundError("прогона нет", run_id="r-1")

    assert error.as_dict() == {
        "error": "not_found",
        "message": "прогона нет",
        "details": {"run_id": "r-1"},
    }


def test_string_form_is_the_message_without_the_code() -> None:
    assert str(ConflictError("расчёт уже идёт")) == "расчёт уже идёт"
