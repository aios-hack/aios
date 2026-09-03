from __future__ import annotations

from typing import Any, Mapping

from backend.application.jarvis.tools.schemas import (
    CONNECTIVITY_LIMIT,
    DEFINITIONS,
    EVENT_TYPES,
    RANK_LIMIT,
    RANK_METRICS,
    SERIES_METRICS,
    ToolDefinition,
)
from backend.infrastructure.llm.chat_events import ToolSpec

BY_NAME: Mapping[str, ToolDefinition] = {item.name: item for item in DEFINITIONS}

__all__ = [
    "BY_NAME",
    "CONNECTIVITY_LIMIT",
    "DEFINITIONS",
    "EVENT_TYPES",
    "RANK_LIMIT",
    "RANK_METRICS",
    "SERIES_METRICS",
    "ToolDefinition",
    "ToolInputError",
    "definition",
    "tool_specs",
    "validate_arguments",
]


class ToolInputError(ValueError):
    pass


def tool_specs() -> tuple[ToolSpec, ...]:
    return tuple(
        ToolSpec(name=item.name, description=item.description, schema=item.schema)
        for item in DEFINITIONS
    )


def definition(name: str) -> ToolDefinition:
    found = BY_NAME.get(name)
    if found is None:
        raise ToolInputError(
            f"tool {name} is not in the Jarvis catalogue: available tools are "
            f"{', '.join(sorted(BY_NAME))}"
        )
    return found


def validate_arguments(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    schema = definition(name).schema
    properties: Mapping[str, Any] = schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ToolInputError(
            f"tool {name} does not accept the fields {', '.join(unknown)}: "
            f"accepted fields are {', '.join(sorted(properties))}"
        )
    for field in schema.get("required", ()):
        if arguments.get(field) is None:
            raise ToolInputError(
                f"tool {name} is missing the required field {field}"
            )
    checked: dict[str, Any] = {}
    for field, value in arguments.items():
        if value is None:
            continue
        checked[field] = _check(name, field, properties[field], value)
    return checked


def _check(tool: str, field: str, rule: Mapping[str, Any], value: Any) -> Any:
    kind = rule.get("type")
    if kind == "string":
        text = value if isinstance(value, str) else str(value)
        allowed = rule.get("enum")
        if allowed and text not in allowed:
            raise ToolInputError(
                f"tool {tool}: field {field}={text!r} is not one of "
                f"{', '.join(allowed)}"
            )
        return text
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolInputError(
                f"tool {tool}: field {field}={value!r} must be an integer"
            )
        return _bounded(tool, field, rule, int(value))
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolInputError(
                f"tool {tool}: field {field}={value!r} must be a number"
            )
        return _bounded(tool, field, rule, float(value))
    if kind == "array":
        if not isinstance(value, (list, tuple)):
            raise ToolInputError(
                f"tool {tool}: field {field} must be an array"
            )
        item_rule = rule.get("items", {})
        return [_check(tool, field, item_rule, item) for item in value]
    return value


def _bounded(tool: str, field: str, rule: Mapping[str, Any], value: Any) -> Any:
    minimum = rule.get("minimum")
    maximum = rule.get("maximum")
    if minimum is not None and value < minimum:
        raise ToolInputError(
            f"tool {tool}: field {field}={value} is below the minimum {minimum}"
        )
    if maximum is not None and value > maximum:
        raise ToolInputError(
            f"tool {tool}: field {field}={value} is above the maximum {maximum}"
        )
    return value
