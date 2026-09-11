from __future__ import annotations

import io

import pytest

from backend.interfaces.cli.runner import (
    EXIT_CONFIGURATION,
    EXIT_CONFLICT,
    EXIT_ERROR,
    EXIT_INFRASTRUCTURE,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_VALIDATION,
    run,
)
from backend.interfaces.http.kit.errors import (
    INTERNAL_CODE,
    internal_body,
    status_for,
    to_response,
)
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

CLI_CASES = (
    (ValidationError, EXIT_VALIDATION),
    (NotFoundError, EXIT_NOT_FOUND),
    (ConflictError, EXIT_CONFLICT),
    (ConfigurationError, EXIT_CONFIGURATION),
    (UnavailableError, EXIT_CONFIGURATION),
    (InfrastructureError, EXIT_INFRASTRUCTURE),
    (ExternalServiceError, EXIT_INFRASTRUCTURE),
    (AiosError, EXIT_ERROR),
)

HTTP_CASES = (
    (ValidationError, 400),
    (NotFoundError, 404),
    (ConflictError, 409),
    (ExternalServiceError, 502),
    (UnavailableError, 503),
    (ConfigurationError, 503),
    (InfrastructureError, 500),
    (AiosError, 500),
)


@pytest.mark.parametrize("kind,expected", CLI_CASES)
def test_cli_exit_codes_follow_the_hierarchy(kind: type[AiosError], expected: int) -> None:
    stderr = io.StringIO()

    def main() -> int:
        raise kind("что-то не так")

    assert run(main, stderr=stderr) == expected


def test_a_clean_run_returns_zero() -> None:
    assert run(lambda: None) == EXIT_OK
    assert run(lambda: 0) == EXIT_OK


def test_a_returned_code_is_passed_through() -> None:
    assert run(lambda: 7) == 7


def test_the_message_and_code_reach_stderr() -> None:
    stderr = io.StringIO()

    def main() -> int:
        raise ValidationError("кейс отклонён", code="runs.case_rejected")

    run(main, stderr=stderr)

    assert stderr.getvalue().strip() == "error[runs.case_rejected]: кейс отклонён"


def test_a_foreign_exception_is_not_swallowed() -> None:
    def main() -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(main)


@pytest.mark.parametrize("kind,expected", HTTP_CASES)
def test_http_status_codes_follow_the_hierarchy(kind: type[AiosError], expected: int) -> None:
    assert status_for(kind("боль")) == expected


def test_the_http_body_always_has_the_three_fields() -> None:
    status, body = to_response(NotFoundError("прогона нет", run_id="r-1"))

    assert status == 404
    assert body == {
        "error": "not_found",
        "message": "прогона нет",
        "details": {"run_id": "r-1"},
    }


def test_a_bare_exception_becomes_a_500_without_leaking_its_text() -> None:
    status, body = to_response(RuntimeError("секрет в тексте"))

    assert status == 500
    assert body == internal_body()
    assert body["error"] == INTERNAL_CODE
    assert "секрет" not in str(body)
