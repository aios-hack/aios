from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SYSTEM_ENV_VAR = "AIOS_JARVIS_SYSTEM"
KNOWLEDGE_ENV_VAR = "AIOS_JARVIS_KNOWLEDGE"
SYSTEM_FILE = "system.json"
KINDS: tuple[str, ...] = ("ui", "service", "domain", "infra", "data", "doc")
MAX_DEPTH = 2


class SystemMapError(RuntimeError):
    pass


def default_system_path() -> Path:
    from_env = os.environ.get(SYSTEM_ENV_VAR)
    if from_env:
        return Path(from_env)
    knowledge = os.environ.get(KNOWLEDGE_ENV_VAR)
    if knowledge:
        return Path(knowledge) / SYSTEM_FILE
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = (
            parent / "frontend" / "public" / "jarvis" / "knowledge" / SYSTEM_FILE
        )
        if candidate.is_file():
            return candidate
    raise SystemMapError(
        "карта системы не найдена: укажите файл переменной окружения "
        f"{SYSTEM_ENV_VAR} или запускайте из корня репозитория с "
        f"frontend/public/jarvis/knowledge/{SYSTEM_FILE}"
    )


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    label: Mapping[str, str]
    kind: str
    summary: Mapping[str, str]
    doc: str | None
    route: Mapping[str, Any] | None
    files: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": dict(self.label),
            "kind": self.kind,
            "summary": dict(self.summary),
            "doc": self.doc,
            "route": dict(self.route) if self.route else None,
            "files": list(self.files),
        }


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    label: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "from": self.source,
            "to": self.target,
            "label": dict(self.label),
        }


class SystemMap:
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_system_path()
        if not self._path.is_file():
            raise SystemMapError(
                f"карта системы {self._path} не найдена: без неё Джарвис не "
                "может рассказать, из чего состоит платформа"
            )
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise SystemMapError(
                f"карта системы {self._path} не разбирается как JSON: {error}"
            ) from error
        if not isinstance(loaded, dict):
            raise SystemMapError(f"карта системы {self._path} не объект JSON")
        self._nodes: dict[str, Node] = {}
        for raw in loaded.get("nodes", ()):
            kind = str(raw.get("kind"))
            if kind not in KINDS:
                raise SystemMapError(
                    f"узел {raw.get('id')!r} карты системы имеет вид {kind!r}, "
                    f"которого нет среди {', '.join(KINDS)}"
                )
            node = Node(
                id=str(raw["id"]),
                label=dict(raw.get("label") or {}),
                kind=kind,
                summary=dict(raw.get("summary") or {}),
                doc=str(raw["doc"]) if raw.get("doc") else None,
                route=dict(raw["route"]) if raw.get("route") else None,
                files=tuple(str(item) for item in raw.get("files", ())),
            )
            self._nodes[node.id] = node
        self._edges: tuple[Edge, ...] = tuple(
            Edge(
                source=str(raw["from"]),
                target=str(raw["to"]),
                label=dict(raw.get("label") or {}),
            )
            for raw in loaded.get("edges", ())
        )
        for edge in self._edges:
            for end in (edge.source, edge.target):
                if end not in self._nodes:
                    raise SystemMapError(
                        f"ребро {edge.source}→{edge.target} карты системы "
                        f"ссылается на узел {end!r}, которого в карте нет"
                    )
        self._source = str(loaded.get("source") or self._path.name)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def source(self) -> str:
        return self._source

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
            for value in node.label.values():
                if str(value).casefold().replace("ё", "е") == key:
                    return node
        for node in self._nodes.values():
            haystack = " ".join(
                [node.id, *(str(value) for value in node.label.values())]
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
                f"узла {focus!r} нет в карте системы: известные узлы — {known}"
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
            label = node.label.get(lang, node.label.get("ru", node.id))
            summary = node.summary.get(lang, node.summary.get("ru", ""))
            first = summary.split(". ")[0].strip()
            if first:
                lines.append(f"{label} — {first}.")
        return lines


_CACHED: SystemMap | None = None


def shared_system_map() -> SystemMap:
    global _CACHED
    if _CACHED is None:
        _CACHED = SystemMap()
    return _CACHED


def reset_shared_system_map() -> None:
    global _CACHED
    _CACHED = None
