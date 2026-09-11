from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from backend.contexts.assistant.infrastructure.docs_index.chunking import (
    chunks_of_knowledge,
    chunks_of_markdown,
    chunks_of_plain,
)
from backend.contexts.assistant.infrastructure.docs_index.index import (
    CACHE_VERSION,
    DocsIndex,
)
from backend.contexts.assistant.infrastructure.docs_index.models import Chunk, Stamp
from backend.contexts.assistant.infrastructure.docs_index.sources import (
    resolve_knowledge_root,
    relative_source,
    collect_stamps,
    stamps_match,
    walk_documents,
    default_cache_path,
    default_roots,
)


def collect_chunks(
    roots: Sequence[Path] | None = None, knowledge_root: Path | None = None
) -> tuple[list[Chunk], list[Stamp]]:
    active = tuple(roots) if roots is not None else default_roots()
    knowledge = resolve_knowledge_root(active, knowledge_root)
    chunks: list[Chunk] = []
    for path in walk_documents(active):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source = relative_source(path, active)
        if path.suffix == ".md":
            chunks.extend(chunks_of_markdown(source, text, "docs"))
        else:
            chunks.extend(chunks_of_plain(source, text, "docs"))
    if knowledge is not None:
        chunks.extend(chunks_of_knowledge(knowledge))
    return chunks, collect_stamps(active, knowledge)


def load_index(
    roots: Sequence[Path] | None = None,
    knowledge_root: Path | None = None,
    cache: Path | None = None,
) -> DocsIndex:
    active = tuple(roots) if roots is not None else default_roots()
    knowledge = resolve_knowledge_root(active, knowledge_root)
    cache_path = cache if cache is not None else default_cache_path()
    fresh = collect_stamps(active, knowledge)
    if cache_path.is_file():
        try:
            stored = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = None
        if (
            isinstance(stored, dict)
            and stored.get("version") == CACHE_VERSION
            and stamps_match(stored.get("stamps", ()), fresh)
        ):
            chunks = [
                Chunk(
                    source=str(row["source"]),
                    heading=str(row["heading"]),
                    anchor=str(row.get("anchor") or ""),
                    text=str(row["text"]),
                    numbers=tuple(float(value) for value in row.get("numbers", ())),
                    scope=str(row.get("scope") or "docs"),
                )
                for row in stored.get("chunks", ())
            ]
            return DocsIndex(chunks, fresh)
    chunks, stamps = collect_chunks(active, knowledge)
    index = DocsIndex(chunks, stamps)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(index.as_dict(), ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass
    return index


class DocsIndexCache:
    def __init__(self) -> None:
        self._index: DocsIndex | None = None

    def get(self) -> DocsIndex:
        if self._index is None:
            self._index = load_index()
        return self._index

    def clear(self) -> None:
        self._index = None


PROCESS_DOCS_CACHE = DocsIndexCache()


def shared_index() -> DocsIndex:
    return PROCESS_DOCS_CACHE.get()


def reset_shared_index() -> None:
    PROCESS_DOCS_CACHE.clear()
