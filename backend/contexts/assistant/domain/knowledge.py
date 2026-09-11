from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

LANGS: tuple[str, ...] = ("ru", "en")
NEUTRAL_FILES: tuple[str, ...] = ("glossary.json", "guide.json", "system.json")
I18N_DIRECTORY = "i18n"
SYSTEM_KINDS: tuple[str, ...] = ("ui", "service", "domain", "infra", "data", "doc")


class KnowledgeSchemaError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TermPlace:
    workspace: str
    view: str
    spotlight: str | None

    def payload(self, what: str) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "view": self.view,
            "what": what,
            "spotlight": self.spotlight,
        }


@dataclass(frozen=True, slots=True)
class Term:
    id: str
    aliases: tuple[str, ...]
    formula: str | None
    unit: str | None
    source: str
    where_in_platform: tuple[TermPlace, ...]
    related: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TermText:
    term: str
    definition: str
    where_in_platform: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScreenControl:
    spotlight: str
    hotkey: str | None


@dataclass(frozen=True, slots=True)
class Screen:
    workspace: str
    view: str
    controls: tuple[ScreenControl, ...]


@dataclass(frozen=True, slots=True)
class ScreenText:
    title: str
    what: str
    how_to_read: str
    controls: tuple[str, ...]
    questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Element:
    id: str
    controls: tuple[ScreenControl, ...]


@dataclass(frozen=True, slots=True)
class ElementText:
    title: str
    what: str
    how_to_read: str
    controls: tuple[str, ...]
    questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SystemNode:
    id: str
    kind: str
    doc: str | None
    route: Mapping[str, Any] | None
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SystemNodeText:
    label: str
    summary: str


@dataclass(frozen=True, slots=True)
class SystemEdge:
    source: str
    target: str


@dataclass(frozen=True, slots=True)
class SystemEdgeText:
    label: str


def _text(raw: Mapping[str, Any], field: str, where: str) -> str:
    value = raw.get(field)
    if isinstance(value, Mapping):
        raise KnowledgeSchemaError(
            f"{where}: field {field!r} still carries a per-language object; "
            "language text belongs in knowledge/i18n/<lang>"
        )
    if value is None:
        return ""
    return str(value)


def _strings(raw: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = raw.get(field) or ()
    if isinstance(value, Mapping):
        raise KnowledgeSchemaError(
            f"field {field!r} still carries a per-language object; "
            "language text belongs in knowledge/i18n/<lang>"
        )
    return tuple(str(item) for item in value)


def parse_term(raw: Mapping[str, Any]) -> Term:
    identifier = str(raw["id"])
    if isinstance(raw.get("term"), Mapping):
        raise KnowledgeSchemaError(
            f"term {identifier!r}: field 'term' belongs in knowledge/i18n/<lang>"
        )
    if isinstance(raw.get("definition"), Mapping):
        raise KnowledgeSchemaError(
            f"term {identifier!r}: field 'definition' belongs in knowledge/i18n/<lang>"
        )
    places: list[TermPlace] = []
    for place in raw.get("where_in_platform", ()):
        if isinstance(place.get("what"), Mapping):
            raise KnowledgeSchemaError(
                f"term {identifier!r}: 'where_in_platform[].what' belongs in "
                "knowledge/i18n/<lang>"
            )
        places.append(
            TermPlace(
                workspace=str(place["workspace"]),
                view=str(place["view"]),
                spotlight=str(place["spotlight"]) if place.get("spotlight") else None,
            )
        )
    formula = raw.get("formula")
    unit = raw.get("unit")
    return Term(
        id=identifier,
        aliases=_strings(raw, "aliases"),
        formula=str(formula) if formula else None,
        unit=str(unit) if unit else None,
        source=str(raw.get("source") or ""),
        where_in_platform=tuple(places),
        related=_strings(raw, "related"),
    )


def parse_term_text(identifier: str, raw: Mapping[str, Any]) -> TermText:
    return TermText(
        term=_text(raw, "term", f"term {identifier!r}"),
        definition=_text(raw, "definition", f"term {identifier!r}"),
        where_in_platform=_strings(raw, "where_in_platform"),
    )


def parse_controls(raw: Mapping[str, Any], where: str) -> tuple[ScreenControl, ...]:
    controls: list[ScreenControl] = []
    for control in raw.get("controls", ()):
        if isinstance(control.get("label"), Mapping):
            raise KnowledgeSchemaError(
                f"{where}: 'controls[].label' belongs in knowledge/i18n/<lang>"
            )
        hotkey = control.get("hotkey")
        controls.append(
            ScreenControl(
                spotlight=str(control["spotlight"]),
                hotkey=str(hotkey) if hotkey else None,
            )
        )
    return tuple(controls)


def parse_screen(raw: Mapping[str, Any]) -> Screen:
    workspace = str(raw["workspace"])
    view = str(raw["view"])
    return Screen(
        workspace=workspace,
        view=view,
        controls=parse_controls(raw, f"screen {workspace}/{view}"),
    )


def parse_screen_text(identifier: str, raw: Mapping[str, Any]) -> ScreenText:
    where = f"screen {identifier!r}"
    return ScreenText(
        title=_text(raw, "title", where),
        what=_text(raw, "what", where),
        how_to_read=_text(raw, "how_to_read", where),
        controls=_strings(raw, "controls"),
        questions=_strings(raw, "questions"),
    )


def parse_element(raw: Mapping[str, Any]) -> Element:
    identifier = str(raw["id"])
    return Element(
        id=identifier,
        controls=parse_controls(raw, f"element {identifier!r}"),
    )


def parse_element_text(identifier: str, raw: Mapping[str, Any]) -> ElementText:
    where = f"element {identifier!r}"
    return ElementText(
        title=_text(raw, "title", where),
        what=_text(raw, "what", where),
        how_to_read=_text(raw, "how_to_read", where),
        controls=_strings(raw, "controls"),
        questions=_strings(raw, "questions"),
    )


def parse_system_node(raw: Mapping[str, Any]) -> SystemNode:
    identifier = str(raw["id"])
    kind = str(raw.get("kind"))
    if kind not in SYSTEM_KINDS:
        raise KnowledgeSchemaError(
            f"system node {identifier!r} has kind {kind!r}, which is not one of "
            f"{', '.join(SYSTEM_KINDS)}"
        )
    if isinstance(raw.get("label"), Mapping) or isinstance(raw.get("summary"), Mapping):
        raise KnowledgeSchemaError(
            f"system node {identifier!r}: 'label' and 'summary' belong in "
            "knowledge/i18n/<lang>"
        )
    doc = raw.get("doc")
    route = raw.get("route")
    return SystemNode(
        id=identifier,
        kind=kind,
        doc=str(doc) if doc else None,
        route=dict(route) if route else None,
        files=_strings(raw, "files"),
    )


def parse_system_node_text(identifier: str, raw: Mapping[str, Any]) -> SystemNodeText:
    where = f"system node {identifier!r}"
    return SystemNodeText(
        label=_text(raw, "label", where),
        summary=_text(raw, "summary", where),
    )


def parse_system_edge(raw: Mapping[str, Any]) -> SystemEdge:
    return SystemEdge(source=str(raw["from"]), target=str(raw["to"]))


def edge_id(edge: SystemEdge) -> str:
    return f"{edge.source}->{edge.target}"


def parse_system_edge_text(identifier: str, raw: Mapping[str, Any]) -> SystemEdgeText:
    return SystemEdgeText(label=_text(raw, "label", f"system edge {identifier!r}"))


def screen_id(workspace: str, view: str) -> str:
    return f"{workspace}/{view}"


def missing_ids(neutral: Sequence[str], localized: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(identifier for identifier in neutral if identifier not in localized))


__all__ = [
    "Element",
    "ElementText",
    "I18N_DIRECTORY",
    "KnowledgeSchemaError",
    "LANGS",
    "NEUTRAL_FILES",
    "SYSTEM_KINDS",
    "Screen",
    "ScreenControl",
    "ScreenText",
    "SystemEdge",
    "SystemEdgeText",
    "SystemNode",
    "SystemNodeText",
    "Term",
    "TermPlace",
    "TermText",
    "edge_id",
    "missing_ids",
    "parse_controls",
    "parse_element",
    "parse_element_text",
    "parse_screen",
    "parse_screen_text",
    "parse_system_edge",
    "parse_system_edge_text",
    "parse_system_node",
    "parse_system_node_text",
    "parse_term",
    "parse_term_text",
    "screen_id",
]
