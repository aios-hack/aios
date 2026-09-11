from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


@dataclass(frozen=True, slots=True)
class Stamp:
    path: str
    mtime: float
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "mtime": self.mtime, "size": self.size}
