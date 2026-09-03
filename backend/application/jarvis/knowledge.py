from __future__ import annotations

import difflib
import json
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

KNOWLEDGE_ENV_VAR = "AIOS_JARVIS_KNOWLEDGE"
FUZZY_CUTOFF = 0.78
LANGS: tuple[str, ...] = ("ru", "en")


class KnowledgeError(RuntimeError):
    pass


def default_knowledge_root() -> Path:
    from_env = os.environ.get(KNOWLEDGE_ENV_VAR)
    if from_env:
        return Path(from_env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "frontend" / "public" / "jarvis" / "knowledge"
        if candidate.is_dir():
            return candidate
    raise KnowledgeError(
        "Jarvis knowledge base not found: point at its directory with the "
        f"{KNOWLEDGE_ENV_VAR} environment variable, or run from the repository "
        "root that contains frontend/public/jarvis/knowledge"
    )


def normalize(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", str(text)).casefold()
    kept = [
        character
        for character in lowered
        if character.isalnum() or character.isspace()
    ]
    return " ".join("".join(kept).split()).replace("ё", "е")


@dataclass(frozen=True, slots=True)
class Term:
    id: str
    term: Mapping[str, str]
    aliases: tuple[str, ...]
    definition: Mapping[str, str]
    formula: str | None
    unit: str | None
    source: str
    where_in_platform: tuple[Mapping[str, Any], ...]
    related: tuple[str, ...]

    def as_payload(self, lang: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "term": self.term.get(lang, self.term.get("ru", self.id)),
            "term_all": dict(self.term),
            "definition": self.definition.get(lang, self.definition.get("ru", "")),
            "formula": self.formula,
            "unit": self.unit,
            "source": self.source,
            "where_in_platform": [
                {
                    "workspace": place["workspace"],
                    "view": place["view"],
                    "what": place["what"].get(lang, place["what"].get("ru", "")),
                    "spotlight": place.get("spotlight"),
                }
                for place in self.where_in_platform
            ],
            "related": list(self.related),
            "provenance": "knowledge",
        }


@dataclass(frozen=True, slots=True)
class Screen:
    workspace: str
    view: str
    title: Mapping[str, str]
    what: Mapping[str, str]
    how_to_read: Mapping[str, str]
    controls: tuple[Mapping[str, Any], ...]
    questions: Mapping[str, Sequence[str]]

    def as_payload(self, lang: str) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "view": self.view,
            "title": self.title.get(lang, self.title.get("ru", "")),
            "what": self.what.get(lang, self.what.get("ru", "")),
            "how_to_read": self.how_to_read.get(lang, self.how_to_read.get("ru", "")),
            "controls": [
                {
                    "label": control["label"].get(lang, control["label"].get("ru", "")),
                    "spotlight": control["spotlight"],
                    "hotkey": control.get("hotkey"),
                }
                for control in self.controls
            ],
            "questions": list(self.questions.get(lang, self.questions.get("ru", ()))),
            "provenance": "knowledge",
        }


def _load(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise KnowledgeError(
            f"knowledge base file {path.name} not found at {path}: without it "
            "Jarvis cannot answer questions about terms or screens"
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise KnowledgeError(
            f"knowledge base file {path} does not parse as JSON: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise KnowledgeError(
            f"knowledge base file {path} is not a JSON object"
        )
    return loaded


class Knowledge:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else default_knowledge_root()
        glossary = _load(self._root / "glossary.json")
        guide = _load(self._root / "guide.json")
        self._terms: dict[str, Term] = {}
        self._index: dict[str, str] = {}
        for raw in glossary.get("terms", ()):
            term = Term(
                id=str(raw["id"]),
                term=dict(raw["term"]),
                aliases=tuple(str(item) for item in raw.get("aliases", ())),
                definition=dict(raw["definition"]),
                formula=raw.get("formula"),
                unit=raw.get("unit"),
                source=str(raw["source"]),
                where_in_platform=tuple(raw.get("where_in_platform", ())),
                related=tuple(str(item) for item in raw.get("related", ())),
            )
            self._terms[term.id] = term
            for key in (term.id, *term.term.values(), *term.aliases):
                self._index.setdefault(normalize(key), term.id)
        self._screens: dict[tuple[str, str], Screen] = {}
        for raw in guide.get("screens", ()):
            screen = Screen(
                workspace=str(raw["workspace"]),
                view=str(raw["view"]),
                title=dict(raw["title"]),
                what=dict(raw["what"]),
                how_to_read=dict(raw["how_to_read"]),
                controls=tuple(raw.get("controls", ())),
                questions={
                    lang: tuple(values)
                    for lang, values in raw.get("questions", {}).items()
                },
            )
            self._screens[(screen.workspace, screen.view)] = screen
        self._elements: tuple[Mapping[str, Any], ...] = tuple(
            guide.get("elements", ())
        )

    @property
    def root(self) -> Path:
        return self._root

    @property
    def term_count(self) -> int:
        return len(self._terms)

    @property
    def screen_count(self) -> int:
        return len(self._screens)

    def terms(self) -> tuple[Term, ...]:
        return tuple(self._terms.values())

    def screens(self) -> tuple[Screen, ...]:
        return tuple(self._screens.values())

    def elements(self) -> tuple[Mapping[str, Any], ...]:
        return self._elements

    def spotlights(self) -> tuple[str, ...]:
        found: set[str] = set()
        for screen in self._screens.values():
            for control in screen.controls:
                found.add(str(control["spotlight"]))
        for element in self._elements:
            for control in element.get("controls", ()):
                found.add(str(control["spotlight"]))
        for term in self._terms.values():
            for place in term.where_in_platform:
                spotlight = place.get("spotlight")
                if spotlight:
                    found.add(str(spotlight))
        return tuple(sorted(found))

    def find_term(self, query: str) -> Term | None:
        key = normalize(query)
        if not key:
            return None
        found = self._index.get(key)
        if found is not None:
            return self._terms[found]
        for candidate, identifier in self._index.items():
            if key in candidate.split() or candidate in key.split():
                return self._terms[identifier]
        close = difflib.get_close_matches(key, self._index, n=1, cutoff=FUZZY_CUTOFF)
        if close:
            return self._terms[self._index[close[0]]]
        return None

    def screen(self, workspace: str, view: str) -> Screen | None:
        return self._screens.get((workspace, view))

    def find_screen(self, query: str) -> Screen | None:
        key = normalize(query)
        if not key:
            return None
        best: tuple[int, Screen] | None = None
        for screen in self._screens.values():
            score = 0
            haystacks = [
                normalize(f"{screen.workspace} {screen.view}"),
                *(normalize(value) for value in screen.title.values()),
            ]
            for control in screen.controls:
                haystacks.extend(
                    normalize(value) for value in control["label"].values()
                )
            for haystack in haystacks:
                if key == haystack:
                    score += 10
                elif key in haystack or haystack in key:
                    score += 4
                else:
                    words = set(key.split()) & set(haystack.split())
                    score += len(words)
            if score > 0 and (best is None or score > best[0]):
                best = (score, screen)
        return best[1] if best is not None else None
