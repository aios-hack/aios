from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

DOCS_ENV_VAR = "AIOS_JARVIS_DOCS"
OUT_ENV_VAR = "AIOS_OUT_DIR"
CACHE_NAME = "docs-index.json"
CACHE_VERSION = 2
CHUNK_LIMIT = 1200
CHUNK_OVERLAP = 150
BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_K = 4
MAX_K = 6
SNIPPET_LIMIT = 420
SCOPES: tuple[str, ...] = ("docs", "knowledge", "all")
PLANNING_SOURCES: tuple[str, ...] = (
    "JARVIS_V2.md",
    "FINAL_PLAN.md",
    "BACKLOG.md",
    "AUDIT_PLAN_2026-09-08.md",
    "DISCUSSIONS.md",
)
PLANNING_PENALTY = 0.45
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
TOKEN_PATTERN = re.compile(r"[0-9a-zA-Zа-яёА-ЯЁ]+")
NUMBER_PATTERN = re.compile(
    r"(?<![\w.,])[-−]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\w])"
    r"|(?<![\w.,])[-−]?\d+(?:[.,]\d+)?(?![\w])"
)
SLUG_DROP = re.compile(r"[^0-9a-zA-Zа-яё\- ]+")
RU_SUFFIXES: tuple[str, ...] = (
    "ированием",
    "ированный",
    "ированная",
    "ированное",
    "ирования",
    "ированию",
    "ировании",
    "ировать",
    "ениями",
    "ениям",
    "ениях",
    "ением",
    "ений",
    "ения",
    "ению",
    "ении",
    "ение",
    "ами",
    "ями",
    "ого",
    "его",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ой",
    "ей",
    "ый",
    "ий",
    "ые",
    "ие",
    "ая",
    "яя",
    "ое",
    "ее",
    "ов",
    "ев",
    "ах",
    "ях",
    "ам",
    "ям",
    "ую",
    "юю",
    "ю",
    "я",
    "й",
    "ь",
    "ы",
    "и",
    "а",
    "е",
    "у",
    "о",
)
EN_SUFFIXES: tuple[str, ...] = ("ing", "ed", "es", "s")
MIN_STEM_LENGTH = 4
ROOT_MARKDOWN_LIMIT = 40
HEADING_WEIGHT = 2


class DocsIndexError(RuntimeError):
    pass


def repository_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise DocsIndexError(
        "корень репозитория не найден: файла pyproject.toml нет ни в одном "
        f"родительском каталоге {here}"
    )


def default_cache_path() -> Path:
    out_dir = os.environ.get(OUT_ENV_VAR)
    base = Path(out_dir) if out_dir else repository_root() / "out"
    return base / "jarvis" / CACHE_NAME


def default_roots() -> tuple[Path, ...]:
    from_env = os.environ.get(DOCS_ENV_VAR)
    if from_env:
        return tuple(
            Path(part.strip()) for part in from_env.split(";") if part.strip()
        )
    root = repository_root()
    found = [root]
    external = root.parent / "docs"
    if external.is_dir():
        found.append(external)
    return tuple(found)


def slug(heading: str) -> str:
    lowered = heading.casefold().replace("ё", "е")
    cleaned = SLUG_DROP.sub("", lowered)
    return "#" + "-".join(cleaned.split())


def stem(token: str) -> str:
    if len(token) < MIN_STEM_LENGTH:
        return token
    for suffix in EN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM_LENGTH:
            return token[: -len(suffix)]
    for suffix in RU_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM_LENGTH:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    lowered = text.casefold().replace("ё", "е")
    return [stem(match.group(0)) for match in TOKEN_PATTERN.finditer(lowered)]


def numbers_in(text: str) -> list[float]:
    found: list[float] = []
    seen: set[float] = set()
    for match in NUMBER_PATTERN.finditer(text):
        cleaned = match.group(0).replace("−", "-")
        for space in (" ", " ", " "):
            cleaned = cleaned.replace(space, "")
        if cleaned.count(",") == 1 and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if value in seen:
            continue
        seen.add(value)
        found.append(value)
    return found


@dataclass(frozen=True, slots=True)
class Chunk:
    source: str
    heading: str
    anchor: str
    text: str
    numbers: tuple[float, ...]
    scope: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "heading": self.heading,
            "anchor": self.anchor,
            "text": self.text,
            "numbers": list(self.numbers),
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class Hit:
    source: str
    heading: str
    anchor: str
    snippet: str
    text: str
    score: float
    numbers: tuple[float, ...]
    scope: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "heading": self.heading,
            "anchor": self.anchor,
            "snippet": self.snippet,
            "text": self.text,
            "score": round(self.score, 4),
            "numbers": list(self.numbers),
            "scope": self.scope,
        }


def _split_sections(text: str) -> list[tuple[str, str]]:
    trail: list[str] = []
    body: list[str] = []
    sections: list[tuple[str, str]] = []
    fence = False
    heading = ""
    for line in text.splitlines():
        if FENCE_PATTERN.match(line):
            fence = not fence
            body.append(line)
            continue
        match = None if fence else HEADING_PATTERN.match(line)
        if match is None:
            body.append(line)
            continue
        collected = "\n".join(body).strip()
        if collected:
            sections.append((heading, collected))
        body = []
        level = len(match.group(1))
        title = match.group(2).strip()
        del trail[level - 1 :]
        while len(trail) < level - 1:
            trail.append("")
        trail.append(title)
        heading = " › ".join(part for part in trail if part)
    collected = "\n".join(body).strip()
    if collected:
        sections.append((heading, collected))
    return sections


def _cut(
    text: str, limit: int = CHUNK_LIMIT, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            window = text.rfind("\n", start + limit // 2, end)
            if window > start:
                end = window
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def chunks_of_markdown(source: str, text: str, scope: str) -> list[Chunk]:
    collected: list[Chunk] = []
    for heading, body in _split_sections(text):
        title = heading or source
        anchor = slug(title.split("›")[-1].strip()) if heading else ""
        for piece in _cut(body):
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
        for piece in _cut(text.strip())
    ]


def _term_text(entry: Mapping[str, Any]) -> tuple[str, str]:
    term = entry.get("term") or {}
    definition = entry.get("definition") or {}
    names = " / ".join(str(value) for value in term.values() if value)
    body_parts = [str(value) for value in definition.values() if value]
    for key in ("formula", "unit", "source"):
        value = entry.get(key)
        if value:
            body_parts.append(f"{key}: {value}")
    aliases = entry.get("aliases") or ()
    if aliases:
        body_parts.append("синонимы: " + ", ".join(str(item) for item in aliases))
    return names or str(entry.get("id", "")), "\n".join(body_parts)


def _screen_text(entry: Mapping[str, Any]) -> tuple[str, str]:
    title = entry.get("title") or {}
    names = " / ".join(str(value) for value in title.values() if value)
    parts: list[str] = []
    for key in ("what", "how_to_read"):
        section = entry.get(key) or {}
        parts.extend(str(value) for value in section.values() if value)
    for control in entry.get("controls", ()):
        label = control.get("label") or {}
        labels = " / ".join(str(value) for value in label.values() if value)
        hotkey = control.get("hotkey")
        spotlight = control.get("spotlight")
        parts.append(
            f"элемент: {labels}"
            + (f" — горячая клавиша {hotkey}" if hotkey else "")
            + (f" — якорь {spotlight}" if spotlight else "")
        )
    for values in (entry.get("questions") or {}).values():
        parts.extend(str(item) for item in values)
    workspace = entry.get("workspace")
    view = entry.get("view")
    return f"{names} ({workspace}/{view})", "\n".join(parts)


def chunks_of_knowledge(root: Path) -> list[Chunk]:
    collected: list[Chunk] = []
    glossary = root / "glossary.json"
    if glossary.is_file():
        loaded = json.loads(glossary.read_text(encoding="utf-8"))
        for entry in loaded.get("terms", ()):
            heading, body = _term_text(entry)
            if not body:
                continue
            collected.append(
                Chunk(
                    source="knowledge/glossary.json",
                    heading=heading,
                    anchor=slug(str(entry.get("id", heading))),
                    text=f"{heading}\n{body}",
                    numbers=tuple(numbers_in(body)),
                    scope="knowledge",
                )
            )
    guide = root / "guide.json"
    if guide.is_file():
        loaded = json.loads(guide.read_text(encoding="utf-8"))
        for entry in loaded.get("screens", ()):
            heading, body = _screen_text(entry)
            collected.append(
                Chunk(
                    source="knowledge/guide.json",
                    heading=heading,
                    anchor=slug(f"{entry.get('workspace')}-{entry.get('view')}"),
                    text=f"{heading}\n{body}",
                    numbers=tuple(numbers_in(body)),
                    scope="knowledge",
                )
            )
        for entry in loaded.get("elements", ()):
            title = entry.get("title") or {}
            names = " / ".join(str(value) for value in title.values() if value)
            parts: list[str] = []
            for key in ("what", "how_to_read"):
                section = entry.get(key) or {}
                parts.extend(str(value) for value in section.values() if value)
            for control in entry.get("controls", ()):
                label = control.get("label") or {}
                parts.append(
                    " / ".join(str(value) for value in label.values() if value)
                )
            body = "\n".join(part for part in parts if part)
            if not body:
                continue
            collected.append(
                Chunk(
                    source="knowledge/guide.json",
                    heading=names or str(entry.get("id", "")),
                    anchor=slug(str(entry.get("id", names))),
                    text=f"{names}\n{body}",
                    numbers=tuple(numbers_in(body)),
                    scope="knowledge",
                )
            )
    return collected


def _relative(path: Path, roots: Sequence[Path]) -> str:
    for root in roots:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.name


def _walk(roots: Sequence[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md"))[:ROOT_MARKDOWN_LIMIT]:
            if path not in seen:
                seen.add(path)
                found.append(path)
        readme = root / "config" / "README.md"
        if readme.is_file() and readme not in seen:
            seen.add(readme)
            found.append(readme)
        checkpoints = root / "checkpoints"
        if checkpoints.is_dir():
            for path in sorted(checkpoints.glob("*.md")):
                if path not in seen:
                    seen.add(path)
                    found.append(path)
        for path in sorted(root.glob("*.txt")):
            if path not in seen:
                seen.add(path)
                found.append(path)
    return found


def _knowledge_root(roots: Sequence[Path], given: Path | None) -> Path | None:
    if given is not None:
        return given if given.is_dir() else None
    for root in roots:
        candidate = root / "frontend" / "public" / "jarvis" / "knowledge"
        if candidate.is_dir():
            return candidate
    return None


@dataclass(frozen=True, slots=True)
class Stamp:
    path: str
    mtime: float
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "mtime": self.mtime, "size": self.size}


def _stamp_of(path: Path) -> Stamp:
    info = path.stat()
    return Stamp(path=str(path), mtime=info.st_mtime, size=info.st_size)


def _stamps(roots: Sequence[Path], knowledge: Path | None) -> list[Stamp]:
    collected = [_stamp_of(path) for path in _walk(roots) if path.is_file()]
    if knowledge is not None:
        for name in ("glossary.json", "guide.json"):
            path = knowledge / name
            if path.is_file():
                collected.append(_stamp_of(path))
    return collected


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
                f"область поиска {scope!r} не существует: допустимые значения — "
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
                    snippet=_snippet(chunk.text, terms),
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


def _snippet(text: str, terms: Sequence[str]) -> str:
    if len(text) <= SNIPPET_LIMIT:
        return text
    wanted = set(terms)
    best = 0
    best_score = -1
    folded = text.casefold().replace("ё", "е")
    for match in TOKEN_PATTERN.finditer(folded):
        if stem(match.group(0)) not in wanted:
            continue
        start = max(0, match.start() - SNIPPET_LIMIT // 3)
        window = folded[start : start + SNIPPET_LIMIT]
        score = sum(
            1
            for item in TOKEN_PATTERN.finditer(window)
            if stem(item.group(0)) in wanted
        )
        if score > best_score:
            best_score = score
            best = start
    piece = text[best : best + SNIPPET_LIMIT].strip()
    prefix = "…" if best > 0 else ""
    suffix = "…" if best + SNIPPET_LIMIT < len(text) else ""
    return f"{prefix}{piece}{suffix}"


def collect_chunks(
    roots: Sequence[Path] | None = None, knowledge_root: Path | None = None
) -> tuple[list[Chunk], list[Stamp]]:
    active = tuple(roots) if roots is not None else default_roots()
    knowledge = _knowledge_root(active, knowledge_root)
    chunks: list[Chunk] = []
    for path in _walk(active):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source = _relative(path, active)
        if path.suffix == ".md":
            chunks.extend(chunks_of_markdown(source, text, "docs"))
        else:
            chunks.extend(chunks_of_plain(source, text, "docs"))
    if knowledge is not None:
        chunks.extend(chunks_of_knowledge(knowledge))
    return chunks, _stamps(active, knowledge)


def _stamps_match(
    stored: Sequence[Mapping[str, Any]], fresh: Sequence[Stamp]
) -> bool:
    if len(stored) != len(fresh):
        return False
    left = {
        str(item.get("path")): (
            float(item.get("mtime", 0.0)),
            int(item.get("size", 0)),
        )
        for item in stored
    }
    right = {stamp.path: (stamp.mtime, stamp.size) for stamp in fresh}
    return left == right


def load_index(
    roots: Sequence[Path] | None = None,
    knowledge_root: Path | None = None,
    cache: Path | None = None,
) -> DocsIndex:
    active = tuple(roots) if roots is not None else default_roots()
    knowledge = _knowledge_root(active, knowledge_root)
    cache_path = cache if cache is not None else default_cache_path()
    fresh = _stamps(active, knowledge)
    if cache_path.is_file():
        try:
            stored = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = None
        if (
            isinstance(stored, dict)
            and stored.get("version") == CACHE_VERSION
            and _stamps_match(stored.get("stamps", ()), fresh)
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


_CACHED: DocsIndex | None = None


def shared_index() -> DocsIndex:
    global _CACHED
    if _CACHED is None:
        _CACHED = load_index()
    return _CACHED


def reset_shared_index() -> None:
    global _CACHED
    _CACHED = None
