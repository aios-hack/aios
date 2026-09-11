from __future__ import annotations

from backend.shared.errors import (
    DomainError,
    ExternalServiceError,
    InfrastructureError,
    NotFoundError,
    UnavailableError,
    ValidationError,
)


class SessionError(DomainError):
    default_code = "assistant.session"


class ToolFailure(DomainError):
    default_code = "assistant.tool"


class ToolInputError(ValidationError):
    default_code = "assistant.tool.input"


class RouteError(ValidationError):
    default_code = "assistant.route"


class ArtifactError(NotFoundError):
    default_code = "assistant.artifact"


class RunError(NotFoundError):
    default_code = "assistant.run"


class DocsIndexError(InfrastructureError):
    default_code = "assistant.docs_index"


class KnowledgeError(InfrastructureError):
    default_code = "assistant.knowledge"


class SystemMapError(InfrastructureError):
    default_code = "assistant.system_map"


class SessionDiskError(InfrastructureError):
    default_code = "assistant.session.disk"


class UpstreamError(ExternalServiceError):
    default_code = "assistant.llm.upstream"


class NoApiKeyError(UnavailableError):
    default_code = "assistant.no_api_key"


class TtsError(ExternalServiceError):
    default_code = "assistant.tts"


class SttError(ExternalServiceError):
    default_code = "assistant.stt"


__all__ = [
    "ArtifactError",
    "DocsIndexError",
    "KnowledgeError",
    "NoApiKeyError",
    "RouteError",
    "RunError",
    "SessionDiskError",
    "SessionError",
    "SttError",
    "SystemMapError",
    "ToolFailure",
    "ToolInputError",
    "TtsError",
    "UpstreamError",
]
