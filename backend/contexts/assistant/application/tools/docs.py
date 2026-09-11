from __future__ import annotations

from typing import Any, Mapping

from backend.contexts.assistant.infrastructure.docs_index import (
    DEFAULT_K,
    MAX_K,
    DocsIndexError,
    shared_index,
)
from backend.contexts.assistant.application.tools.context import Card, ToolContext, ToolFailure

PROVENANCE = "docs"
NO_HITS = "no-doc-hits"


def _index(context: ToolContext) -> Any:
    if context.docs is not None:
        return context.docs
    return shared_index()


def search_docs(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolFailure(
            "the documentation query is empty: there is nothing to search for, name "
            "the topic with words from the question"
        )
    scope = str(arguments.get("scope") or "all")
    requested = arguments.get("k")
    k = int(requested) if isinstance(requested, (int, float)) else DEFAULT_K
    k = max(1, min(k, MAX_K))
    index = _index(context)
    try:
        hits = index.search(query, k, scope)
    except DocsIndexError as error:
        raise ToolFailure(str(error)) from error
    if not hits:
        raise ToolFailure(
            f"{NO_HITS}: the documentation index ({index.size()} chunks from "
            f"{len(index.sources())} files) holds no match for the query "
            f"{query!r} in scope {scope}; the content of documents must not "
            "be invented"
        )
    head = hits[0]
    payload: dict[str, Any] = {
        "query": query,
        "scope": scope,
        "terms": _terms(query),
        "hits": [hit.as_dict() for hit in hits],
        "indexed_chunks": index.size(),
        "indexed_files": len(index.sources()),
    }
    return Card(
        type="doc",
        title=_title(head.source, head.heading),
        payload=payload,
        provenance=PROVENANCE,
    )


def _terms(query: str) -> list[str]:
    words: list[str] = []
    for raw in query.replace("«", " ").replace("»", " ").split():
        cleaned = raw.strip(".,;:!?()[]{}\"'—–-")
        if len(cleaned) >= 3 and cleaned not in words:
            words.append(cleaned)
    return words


def _title(source: str, heading: str) -> str:
    tail = heading.split("›")[-1].strip()
    if not tail or tail == source:
        return source
    return f"{source} › {tail}"
