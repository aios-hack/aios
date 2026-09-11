from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.contexts.assistant.domain.errors import KnowledgeError
from backend.contexts.assistant.domain.knowledge import (
    I18N_DIRECTORY,
    LANGS,
    Element,
    ElementText,
    Screen,
    ScreenText,
    Term,
    TermText,
    parse_element,
    parse_element_text,
    parse_screen,
    parse_screen_text,
    parse_term,
    parse_term_text,
    screen_id,
)
from backend.shared.json_io import read_json
from backend.shared.settings import Settings

KNOWLEDGE_ENV_VAR = "AIOS_JARVIS_KNOWLEDGE"
FUZZY_CUTOFF = 0.78
DEFAULT_LANG = "ru"
PROVENANCE = "knowledge"


def default_knowledge_root() -> Path:
    from_env = Settings.from_env().jarvis_knowledge
    if from_env is not None:
        return from_env
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


def _load(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise KnowledgeError(
            f"knowledge base file {path.name} not found at {path}: without it "
            "Jarvis cannot answer questions about terms or screens"
        )
    loaded = read_json(path)
    if not isinstance(loaded, Mapping):
        raise KnowledgeError(f"knowledge base file {path} is not a JSON object")
    return loaded


def _at(values: Sequence[str], index: int) -> str:
    return values[index] if index < len(values) else ""


@dataclass(frozen=True, slots=True)
class LocalizedTerm:
    term: Term
    text: TermText

    @property
    def id(self) -> str:
        return self.term.id

    @property
    def aliases(self) -> tuple[str, ...]:
        return self.term.aliases

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.term.id,
            "term": self.text.term,
            "definition": self.text.definition,
            "formula": self.term.formula,
            "unit": self.term.unit,
            "source": self.term.source,
            "where_in_platform": [
                place.payload(_at(self.text.where_in_platform, index))
                for index, place in enumerate(self.term.where_in_platform)
            ],
            "related": list(self.term.related),
            "provenance": PROVENANCE,
        }


@dataclass(frozen=True, slots=True)
class LocalizedScreen:
    screen: Screen
    text: ScreenText

    @property
    def workspace(self) -> str:
        return self.screen.workspace

    @property
    def view(self) -> str:
        return self.screen.view

    @property
    def title(self) -> str:
        return self.text.title

    def as_payload(self) -> dict[str, Any]:
        return {
            "workspace": self.screen.workspace,
            "view": self.screen.view,
            "title": self.text.title,
            "what": self.text.what,
            "how_to_read": self.text.how_to_read,
            "controls": [
                {
                    "label": _at(self.text.controls, index),
                    "spotlight": control.spotlight,
                    "hotkey": control.hotkey,
                }
                for index, control in enumerate(self.screen.controls)
            ],
            "questions": list(self.text.questions),
            "provenance": PROVENANCE,
        }


@dataclass(frozen=True, slots=True)
class LocalizedElement:
    element: Element
    text: ElementText

    @property
    def id(self) -> str:
        return self.element.id

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.element.id,
            "title": self.text.title,
            "what": self.text.what,
            "how_to_read": self.text.how_to_read,
            "controls": [
                {
                    "label": _at(self.text.controls, index),
                    "spotlight": control.spotlight,
                    "hotkey": control.hotkey,
                }
                for index, control in enumerate(self.element.controls)
            ],
            "questions": list(self.text.questions),
        }


class KnowledgeStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else default_knowledge_root()
        glossary = _load(self._root / "glossary.json")
        guide = _load(self._root / "guide.json")
        self._terms: dict[str, Term] = {}
        self._index: dict[str, str] = {}
        for raw in glossary.get("terms", ()):
            term = parse_term(raw)
            self._terms[term.id] = term
            for key in (term.id, *term.aliases):
                self._index.setdefault(normalize(key), term.id)
        self._screens: dict[str, Screen] = {}
        for raw in guide.get("screens", ()):
            screen = parse_screen(raw)
            self._screens[screen_id(screen.workspace, screen.view)] = screen
        self._elements: dict[str, Element] = {}
        for raw in guide.get("elements", ()):
            element = parse_element(raw)
            self._elements[element.id] = element
        self._texts: dict[str, dict[str, Any]] = {}
        for lang in LANGS:
            self._texts[lang] = self._load_language(lang)
        for lang in LANGS:
            for identifier, text in self._texts[lang]["terms"].items():
                self._index.setdefault(normalize(text.term), identifier)

    def _load_language(self, lang: str) -> dict[str, Any]:
        base = self._root / I18N_DIRECTORY / lang
        glossary = _load(base / "glossary.json")
        guide = _load(base / "guide.json")
        terms = {
            identifier: parse_term_text(identifier, raw)
            for identifier, raw in glossary.get("terms", {}).items()
        }
        screens = {
            identifier: parse_screen_text(identifier, raw)
            for identifier, raw in guide.get("screens", {}).items()
        }
        elements = {
            identifier: parse_element_text(identifier, raw)
            for identifier, raw in guide.get("elements", {}).items()
        }
        missing = sorted(set(self._terms) - set(terms))
        if missing:
            raise KnowledgeError(
                f"knowledge base language {lang!r} has no text for terms {missing}"
            )
        return {
            "terms": terms,
            "screens": screens,
            "elements": elements,
            "glossary_notice": str(glossary.get("notice") or ""),
            "guide_notice": str(guide.get("notice") or ""),
        }

    def _lang(self, lang: str) -> str:
        return lang if lang in self._texts else DEFAULT_LANG

    @property
    def root(self) -> Path:
        return self._root

    @property
    def term_count(self) -> int:
        return len(self._terms)

    @property
    def screen_count(self) -> int:
        return len(self._screens)

    def notice(self, lang: str, catalog: str = "glossary") -> str:
        key = "glossary_notice" if catalog == "glossary" else "guide_notice"
        return str(self._texts[self._lang(lang)][key])

    def localized(self, lang: str) -> tuple[LocalizedTerm, ...]:
        texts = self._texts[self._lang(lang)]["terms"]
        return tuple(
            LocalizedTerm(term, texts[identifier])
            for identifier, term in self._terms.items()
        )

    def terms(self, lang: str = DEFAULT_LANG) -> tuple[LocalizedTerm, ...]:
        return self.localized(lang)

    def screens(self, lang: str = DEFAULT_LANG) -> tuple[LocalizedScreen, ...]:
        texts = self._texts[self._lang(lang)]["screens"]
        return tuple(
            LocalizedScreen(screen, texts[identifier])
            for identifier, screen in self._screens.items()
            if identifier in texts
        )

    def elements(self, lang: str = DEFAULT_LANG) -> tuple[LocalizedElement, ...]:
        texts = self._texts[self._lang(lang)]["elements"]
        return tuple(
            LocalizedElement(element, texts[identifier])
            for identifier, element in self._elements.items()
            if identifier in texts
        )

    def spotlights(self) -> tuple[str, ...]:
        found: set[str] = set()
        for screen in self._screens.values():
            for control in screen.controls:
                found.add(control.spotlight)
        for element in self._elements.values():
            for control in element.controls:
                found.add(control.spotlight)
        for term in self._terms.values():
            for place in term.where_in_platform:
                if place.spotlight:
                    found.add(place.spotlight)
        return tuple(sorted(found))

    def term(self, identifier: str, lang: str = DEFAULT_LANG) -> LocalizedTerm | None:
        found = self._terms.get(identifier)
        if found is None:
            return None
        return LocalizedTerm(found, self._texts[self._lang(lang)]["terms"][identifier])

    def find_term(self, query: str, lang: str = DEFAULT_LANG) -> LocalizedTerm | None:
        key = normalize(query)
        if not key:
            return None
        found = self._index.get(key)
        if found is None:
            for candidate, identifier in self._index.items():
                if key in candidate.split() or candidate in key.split():
                    found = identifier
                    break
        if found is None:
            close = difflib.get_close_matches(key, self._index, n=1, cutoff=FUZZY_CUTOFF)
            if close:
                found = self._index[close[0]]
        if found is None:
            return None
        return self.term(found, lang)

    def screen(
        self, workspace: str, view: str, lang: str = DEFAULT_LANG
    ) -> LocalizedScreen | None:
        identifier = screen_id(workspace, view)
        found = self._screens.get(identifier)
        texts = self._texts[self._lang(lang)]["screens"]
        if found is None or identifier not in texts:
            return None
        return LocalizedScreen(found, texts[identifier])

    def find_screen(self, query: str, lang: str = DEFAULT_LANG) -> LocalizedScreen | None:
        key = normalize(query)
        if not key:
            return None
        best: tuple[int, LocalizedScreen] | None = None
        for screen in self.screens(lang):
            score = 0
            haystacks = [
                normalize(f"{screen.workspace} {screen.view}"),
                normalize(screen.title),
            ]
            haystacks.extend(normalize(label) for label in screen.text.controls)
            for haystack in haystacks:
                if key == haystack:
                    score += 10
                elif key in haystack or haystack in key:
                    score += 4
                else:
                    score += len(set(key.split()) & set(haystack.split()))
            if score > 0 and (best is None or score > best[0]):
                best = (score, screen)
        return best[1] if best is not None else None


Knowledge = KnowledgeStore


__all__ = [
    "DEFAULT_LANG",
    "FUZZY_CUTOFF",
    "KNOWLEDGE_ENV_VAR",
    "Knowledge",
    "KnowledgeError",
    "KnowledgeStore",
    "LocalizedElement",
    "LocalizedScreen",
    "LocalizedTerm",
    "default_knowledge_root",
    "normalize",
]
