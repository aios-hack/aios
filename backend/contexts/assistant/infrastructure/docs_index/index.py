from __future__ import annotations

import math
from collections import Counter
from typing import Any, Sequence

from backend.contexts.assistant.domain.errors import DocsIndexError
from backend.contexts.assistant.infrastructure.docs_index.models import Chunk, Hit, Stamp
from backend.contexts.assistant.infrastructure.docs_index.text import (
    build_snippet,
    tokenize,
)


CACHE_VERSION = 2


BM25_K1 = 1.5


BM25_B = 0.75


DEFAULT_K = 4


MAX_K = 6


SCOPES: tuple[str, ...] = ("docs", "knowledge", "all")


PLANNING_SOURCES: tuple[str, ...] = (
    "JARVIS_V2.md",
    "FINAL_PLAN.md",
    "BACKLOG.md",
    "AUDIT_PLAN_2026-09-08.md",
    "DISCUSSIONS.md",
)


PLANNING_PENALTY = 0.45


HEADING_WEIGHT = 2


def _source_weight(source: str) -> float:
    name = source.replace("\\", "/").rsplit("/", 1)[-1]
    return PLANNING_PENALTY if name in PLANNING_SOURCES else 1.0


def _weighted(chunk: Chunk) -> Counter[str]:
    counter = Counter(tokenize(chunk.text))
    for _ in range(HEADING_WEIGHT):
        counter.update(tokenize(chunk.heading))
    return counter


class DocsIndex:
    def __init__(self, chunks: Sequence[Chunk], stamps: Sequence[Stamp] = ()) -> None:
        self._chunks = tuple(chunks)
        self._stamps = tuple(stamps)
        self._tokens: tuple[Counter[str], ...] = tuple(
            _weighted(chunk) for chunk in self._chunks
        )
        self._lengths = tuple(sum(counter.values()) for counter in self._tokens)
        total = sum(self._lengths)
        self._average = total / len(self._chunks) if self._chunks else 0.0
        document_frequency: Counter[str] = Counter()
        for counter in self._tokens:
            document_frequency.update(counter.keys())
        self._document_frequency = document_frequency

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        return self._chunks

    @property
    def stamps(self) -> tuple[Stamp, ...]:
        return self._stamps

    def size(self) -> int:
        return len(self._chunks)

    def sources(self) -> tuple[str, ...]:
        found: list[str] = []
        for chunk in self._chunks:
            if chunk.source not in found:
                found.append(chunk.source)
        return tuple(found)

    def _idf(self, token: str) -> float:
        count = self._document_frequency.get(token, 0)
        if count == 0:
            return 0.0
        total = len(self._chunks)
        return math.log(1.0 + (total - count + 0.5) / (count + 0.5))

    def search(
        self, query: str, k: int = DEFAULT_K, scope: str = "all"
    ) -> tuple[Hit, ...]:
        if scope not in SCOPES:
            raise DocsIndexError(
                f"search scope {scope!r} does not exist: allowed values are "
                f"{', '.join(SCOPES)}"
            )
        terms = tokenize(query)
        if not terms:
            return ()
        limit = max(1, min(int(k), MAX_K))
        scored: list[tuple[float, int]] = []
        for position, counter in enumerate(self._tokens):
            chunk = self._chunks[position]
            if scope != "all" and chunk.scope != scope:
                continue
            length = self._lengths[position] or 1
            total = 0.0
            for term in terms:
                frequency = counter.get(term, 0)
                if frequency == 0:
                    continue
                norm = frequency * (BM25_K1 + 1.0)
                denominator = frequency + BM25_K1 * (
                    1.0 - BM25_B + BM25_B * length / (self._average or 1.0)
                )
                total += self._idf(term) * norm / denominator
            if total > 0.0:
                scored.append((total * _source_weight(chunk.source), position))
        if not scored:
            return ()
        scored.sort(key=lambda row: (-row[0], row[1]))
        best = scored[0][0] or 1.0
        hits: list[Hit] = []
        for total, position in scored[:limit]:
            chunk = self._chunks[position]
            hits.append(
                Hit(
                    source=chunk.source,
                    heading=chunk.heading,
                    anchor=chunk.anchor,
                    snippet=build_snippet(chunk.text, terms),
                    text=chunk.text,
                    score=total / best,
                    numbers=chunk.numbers,
                    scope=chunk.scope,
                )
            )
        return tuple(hits)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": CACHE_VERSION,
            "stamps": [stamp.as_dict() for stamp in self._stamps],
            "chunks": [chunk.as_dict() for chunk in self._chunks],
        }
