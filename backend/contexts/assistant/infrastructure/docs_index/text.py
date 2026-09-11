from __future__ import annotations

import re
from typing import Sequence


CHUNK_LIMIT = 1200


CHUNK_OVERLAP = 150


SNIPPET_LIMIT = 420


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


def split_sections(text: str) -> list[tuple[str, str]]:
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


def cut_into_pieces(
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


def build_snippet(text: str, terms: Sequence[str]) -> str:
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
