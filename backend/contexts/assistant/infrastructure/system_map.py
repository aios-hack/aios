from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.contexts.assistant.domain.errors import SystemMapError
from backend.contexts.assistant.domain.knowledge import (
    I18N_DIRECTORY,
    LANGS,
    SYSTEM_KINDS,
    SystemEdge,
    SystemEdgeText,
    SystemNode,
    SystemNodeText,
    edge_id,
    parse_system_edge,
    parse_system_edge_text,
    parse_system_node,
    parse_system_node_text,
)
from backend.shared.json_io import read_json
from backend.shared.settings import Settings

SYSTEM_ENV_VAR = "AIOS_JARVIS_SYSTEM"
KNOWLEDGE_ENV_VAR = "AIOS_JARVIS_KNOWLEDGE"
SYSTEM_FILE = "system.json"
KINDS: tuple[str, ...] = SYSTEM_KINDS
MAX_DEPTH = 2
DEFAULT_LANG = "ru"


def default_system_path() -> Path:
    settings = Settings.from_env()
    if settings.jarvis_system is not None:
        return settings.jarvis_system
    if settings.jarvis_knowledge is not None:
        return settings.jarvis_knowledge / SYSTEM_FILE
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = (
            parent / "frontend" / "public" / "jarvis" / "knowledge" / SYSTEM_FILE
        )
        if candidate.is_file():
            return candidate
    raise SystemMapError(
        "the system map was not found: name the file in the "
        f"{SYSTEM_ENV_VAR} environment variable, or run from the repository "
        f"root that holds frontend/public/jarvis/knowledge/{SYSTEM_FILE}"
    )


@dataclass(frozen=True, slots=True)
class Node:
    node: SystemNode
    text: Mapping[str, SystemNodeText]

    @property
    def id(self) -> str:
        return self.node.id

    @property
    def kind(self) -> str:
        return self.node.kind

    @property
    def doc(self) -> str | None:
        return self.node.doc

    @property
    def route(self) -> Mapping[str, Any] | None:
        return self.node.route

    @property
    def files(self) -> tuple[str, ...]:
        return self.node.files

    def label(self, lang: str = DEFAULT_LANG) -> str:
        return self._text(lang).label

    def summary(self, lang: str = DEFAULT_LANG) -> str:
        return self._text(lang).summary

    def _text(self, lang: str) -> SystemNodeText:
        if lang in self.text:
            return self.text[lang]
        return self.text[DEFAULT_LANG]

    def as_dict(self, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        return {
            "id": self.node.id,
            "label": self.label(lang),
            "kind": self.node.kind,
            "summary": self.summary(lang),
            "doc": self.node.doc,
            "route": dict(self.node.route) if self.node.route else None,
            "files": list(self.node.files),
        }


@dataclass(frozen=True, slots=True)
class Edge:
    edge: SystemEdge
    text: Mapping[str, SystemEdgeText]

    @property
    def source(self) -> str:
        return self.edge.source

    @property
    def target(self) -> str:
        return self.edge.target

    def label(self, lang: str = DEFAULT_LANG) -> str:
        if lang in self.text:
            return self.text[lang].label
        return self.text[DEFAULT_LANG].label

    def as_dict(self, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        return {
            "from": self.edge.source,
            "to": self.edge.target,
            "label": self.label(lang),
        }


class SystemMap:
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_system_path()
        if not self._path.is_file():
            raise SystemMapError(
                f"the system map {self._path} was not found: without it Jarvis "
                "cannot say what the platform is made of"
            )
        loaded = read_json(self._path)
        if not isinstance(loaded, Mapping):
            raise SystemMapError(f"the system map {self._path} is not a JSON object")
        texts = self._load_texts()
        self._nodes: dict[str, Node] = {}
        for raw in loaded.get("nodes", ()):
            parsed = parse_system_node(raw)
            per_lang = {
                lang: texts[lang]["nodes"][parsed.id]
                for lang in texts
                if parsed.id in texts[lang]["nodes"]
            }
            if DEFAULT_LANG not in per_lang:
                raise SystemMapError(
                    f"the system map node {parsed.id!r} has no {DEFAULT_LANG} text"
                )
            self._nodes[parsed.id] = Node(parsed, per_lang)
        edges: list[Edge] = []
        for raw in loaded.get("edges", ()):
            parsed = parse_system_edge(raw)
            identifier = edge_id(parsed)
            per_lang = {
                lang: texts[lang]["edges"][identifier]
                for lang in texts
                if identifier in texts[lang]["edges"]
            }
            if DEFAULT_LANG not in per_lang:
                raise SystemMapError(
                    f"the system map edge {identifier!r} has no {DEFAULT_LANG} text"
                )
            edges.append(Edge(parsed, per_lang))
        self._edges: tuple[Edge, ...] = tuple(edges)
        for edge in self._edges:
            for end in (edge.source, edge.target):
                if end not in self._nodes:
                    raise SystemMapError(
                        f"the system map edge {edge.source}->{edge.target} names "
                        f"node {end!r}, which the map does not hold"
                    )
        self._sources = {
            lang: texts[lang]["source"] or self._path.name for lang in texts
        }

    def _load_texts(self) -> dict[str, dict[str, Any]]:
        base = self._path.parent / I18N_DIRECTORY
        texts: dict[str, dict[str, Any]] = {}
        for lang in LANGS:
            path = base / lang / SYSTEM_FILE
            if not path.is_file():
                continue
            loaded = read_json(path)
            texts[lang] = {
                "nodes": {
                    identifier: parse_system_node_text(identifier, raw)
                    for identifier, raw in loaded.get("nodes", {}).items()
                },
                "edges": {
                    identifier: parse_system_edge_text(identifier, raw)
                    for identifier, raw in loaded.get("edges", {}).items()
                },
                "source": str(loaded.get("source") or ""),
            }
        if DEFAULT_LANG not in texts:
            raise SystemMapError(
                f"the system map has no {DEFAULT_LANG} text under {base}"
            )
        return texts

    @property
    def path(self) -> Path:
        return self._path

    @property
    def source(self) -> str:
        return self._sources[DEFAULT_LANG]

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def nodes(self) -> tuple[Node, ...]:
        return tuple(self._nodes.values())

    def edges(self) -> tuple[Edge, ...]:
        return self._edges

    def node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def find(self, query: str) -> Node | None:
        key = query.strip().casefold().replace("ё", "е")
        if not key:
            return None
        found = self._nodes.get(key)
        if found is not None:
            return found
        for node in self._nodes.values():
            if node.id.casefold() == key:
                return node
            for lang in node.text:
                if node.label(lang).casefold().replace("ё", "е") == key:
                    return node
        for node in self._nodes.values():
            haystack = " ".join(
                [node.id, *(node.label(lang) for lang in node.text)]
            ).casefold().replace("ё", "е")
            if key in haystack:
                return node
        return None

    def neighbourhood(
        self, focus: str | None, depth: int = 1
    ) -> tuple[tuple[Node, ...], tuple[Edge, ...]]:
        if focus is None:
            return self.nodes(), self.edges()
        node = self.node(focus)
        if node is None:
            known = ", ".join(sorted(self._nodes))
            raise SystemMapError(
                f"the system map has no node {focus!r}: known nodes are {known}"
            )
        limit = max(1, min(int(depth), MAX_DEPTH))
        reached = {node.id}
        frontier = {node.id}
        for _ in range(limit):
            following: set[str] = set()
            for edge in self._edges:
                if edge.source in frontier and edge.target not in reached:
                    following.add(edge.target)
                if edge.target in frontier and edge.source not in reached:
                    following.add(edge.source)
            if not following:
                break
            reached |= following
            frontier = following
        nodes = tuple(item for item in self._nodes.values() if item.id in reached)
        edges = tuple(
            edge
            for edge in self._edges
            if edge.source in reached and edge.target in reached
        )
        return nodes, edges

    def brief(self, lang: str, ids: Sequence[str] = ()) -> list[str]:
        wanted = tuple(ids) if ids else tuple(self._nodes)
        lines: list[str] = []
        for node_id in wanted:
            node = self._nodes.get(node_id)
            if node is None:
                continue
            first = node.summary(lang).split(". ")[0].strip()
            if first:
                lines.append(f"{node.label(lang)} — {first}.")
        return lines


__all__ = [
    "DEFAULT_LANG",
    "KINDS",
    "KNOWLEDGE_ENV_VAR",
    "MAX_DEPTH",
    "SYSTEM_ENV_VAR",
    "SYSTEM_FILE",
    "Edge",
    "Node",
    "SystemMap",
    "SystemMapError",
    "default_system_path",
]
