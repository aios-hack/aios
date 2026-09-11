from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from backend.contexts.assistant.domain.errors import KnowledgeError
from backend.contexts.assistant.domain.knowledge import LANGS
from backend.contexts.assistant.infrastructure.docs_index.models import Chunk
from backend.contexts.assistant.infrastructure.docs_index.text import (
    cut_into_pieces,
    split_sections,
    numbers_in,
    slug,
)
from backend.contexts.assistant.infrastructure.knowledge import KnowledgeStore


def chunks_of_markdown(source: str, text: str, scope: str) -> list[Chunk]:
    collected: list[Chunk] = []
    for heading, body in split_sections(text):
        title = heading or source
        anchor = slug(title.split("›")[-1].strip()) if heading else ""
        for piece in cut_into_pieces(body):
            collected.append(
                Chunk(
                    source=source,
                    heading=title,
                    anchor=anchor,
                    text=piece,
                    numbers=tuple(numbers_in(piece)),
                    scope=scope,
                )
            )
    return collected


def chunks_of_plain(source: str, text: str, scope: str) -> list[Chunk]:
    return [
        Chunk(
            source=source,
            heading=source,
            anchor="",
            text=piece,
            numbers=tuple(numbers_in(piece)),
            scope=scope,
        )
        for piece in cut_into_pieces(text.strip())
    ]


def _joined(values: Sequence[str]) -> str:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return " / ".join(seen)


def _term_text(store: KnowledgeStore, identifier: str) -> tuple[str, str]:
    per_lang = [store.term(identifier, lang) for lang in LANGS]
    present = [item for item in per_lang if item is not None]
    if not present:
        return identifier, ""
    term = present[0].term
    names = _joined([item.text.term for item in present])
    body_parts = [item.text.definition for item in present if item.text.definition]
    for key, value in (("formula", term.formula), ("unit", term.unit), ("source", term.source)):
        if value:
            body_parts.append(f"{key}: {value}")
    if term.aliases:
        body_parts.append("синонимы: " + ", ".join(term.aliases))
    return names or identifier, chr(10).join(body_parts)


def _screen_text(store: KnowledgeStore, workspace: str, view: str) -> tuple[str, str]:
    per_lang = [store.screen(workspace, view, lang) for lang in LANGS]
    present = [item for item in per_lang if item is not None]
    if not present:
        return f"({workspace}/{view})", ""
    names = _joined([item.text.title for item in present])
    parts: list[str] = []
    for item in present:
        for value in (item.text.what, item.text.how_to_read):
            if value:
                parts.append(value)
    controls = present[0].screen.controls
    for index, control in enumerate(controls):
        labels = _joined([_at_index(item.text.controls, index) for item in present])
        parts.append(
            f"элемент: {labels}"
            + (f" — горячая клавиша {control.hotkey}" if control.hotkey else "")
            + (f" — якорь {control.spotlight}" if control.spotlight else "")
        )
    for item in present:
        parts.extend(item.text.questions)
    return f"{names} ({workspace}/{view})", chr(10).join(part for part in parts if part)


def _element_text(store: KnowledgeStore, identifier: str) -> tuple[str, str]:
    per_lang: list[Any] = []
    for lang in LANGS:
        for element in store.elements(lang):
            if element.id == identifier:
                per_lang.append(element)
    if not per_lang:
        return identifier, ""
    names = _joined([item.text.title for item in per_lang])
    parts: list[str] = []
    for item in per_lang:
        for value in (item.text.what, item.text.how_to_read):
            if value:
                parts.append(value)
    controls = per_lang[0].element.controls
    for index in range(len(controls)):
        parts.append(_joined([_at_index(item.text.controls, index) for item in per_lang]))
    return names or identifier, chr(10).join(part for part in parts if part)


def _at_index(values: Sequence[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def chunks_of_knowledge(root: Path) -> list[Chunk]:
    try:
        store = KnowledgeStore(root)
    except KnowledgeError:
        return []
    collected: list[Chunk] = []
    for term in store.localized("ru"):
        heading, body = _term_text(store, term.id)
        if not body:
            continue
        collected.append(
            Chunk(
                source="knowledge/glossary.json",
                heading=heading,
                anchor=slug(term.id),
                text=heading + chr(10) + body,
                numbers=tuple(numbers_in(body)),
                scope="knowledge",
            )
        )
    for screen in store.screens("ru"):
        heading, body = _screen_text(store, screen.workspace, screen.view)
        collected.append(
            Chunk(
                source="knowledge/guide.json",
                heading=heading,
                anchor=slug(f"{screen.workspace}-{screen.view}"),
                text=heading + chr(10) + body,
                numbers=tuple(numbers_in(body)),
                scope="knowledge",
            )
        )
    for element in store.elements("ru"):
        heading, body = _element_text(store, element.id)
        if not body:
            continue
        collected.append(
            Chunk(
                source="knowledge/guide.json",
                heading=heading,
                anchor=slug(element.id),
                text=heading + chr(10) + body,
                numbers=tuple(numbers_in(body)),
                scope="knowledge",
            )
        )
    return collected
