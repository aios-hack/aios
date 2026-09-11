from __future__ import annotations

import re
from dataclasses import dataclass

ANSWER_MARKER = "---ОТВЕТ---"
ANSWER_MARKER_EN = "---ANSWER---"
MARKER_PATTERN = re.compile(
    r"^[ \t]*-{2,}\s*(?:ОТВЕТ|ANSWER)\s*-{2,}[ \t]*$", re.IGNORECASE | re.MULTILINE
)
ANSWER_LIMIT = 1500


@dataclass(frozen=True, slots=True)
class Split:
    caption: str
    answer: str | None


def split_answer(text: str) -> Split:
    match = MARKER_PATTERN.search(text)
    if match is None:
        return Split(caption=text.strip(), answer=None)
    caption = text[: match.start()].strip()
    answer = text[match.end() :].strip()
    if not answer:
        return Split(caption=caption, answer=None)
    return Split(caption=caption, answer=answer[:ANSWER_LIMIT])


def marker_position(text: str) -> int | None:
    match = MARKER_PATTERN.search(text)
    return match.start() if match is not None else None
