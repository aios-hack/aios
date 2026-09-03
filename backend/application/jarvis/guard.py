from __future__ import annotations

import re
from dataclasses import dataclass
from math import floor, log10
from typing import Any, Iterable, Mapping, Sequence

NUMBER_PATTERN = re.compile(
    r"(?<![\w.,])[-−]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\w])"
    r"|(?<![\w.,])[-−]?\d+(?:[.,]\d+)?(?![\w])"
)
DATE_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{2}\.\d{2}\.\d{4}\b"
    r"|\b(?:19|20)\d{2}\s*(?:год|года|году|г\.|г\b)"
    r"|\b(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*\s+(?:19|20)\d{2}"
)
RULE_PATTERN = re.compile(r"\bR[0-7]\b|\bR\d+\b")
WELL_PATTERN = re.compile(
    r"(?:скважин\w*|well)\s*(?:№|#)?\s*[-—–]?\s*(\d+)", re.IGNORECASE
)
SIGNIFICANT_DIGITS = 2
RELATIVE_TOLERANCE = 5e-3


@dataclass(frozen=True, slots=True)
class GuardResult:
    text: str
    ok: bool
    dropped: tuple[str, ...]

    @property
    def guarded(self) -> bool:
        return True


def _to_float(raw: str) -> float | None:
    cleaned = raw.replace("−", "-").replace(" ", "").replace(" ", "")
    cleaned = cleaned.replace(" ", "")
    if cleaned.count(",") == 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def collect_numbers(value: Any, into: set[float] | None = None) -> set[float]:
    found = into if into is not None else set()
    if isinstance(value, bool):
        return found
    if isinstance(value, (int, float)):
        _add_variants(found, float(value))
        return found
    if isinstance(value, str):
        return found
    if isinstance(value, Mapping):
        for item in value.values():
            collect_numbers(item, found)
        return found
    if isinstance(value, (list, tuple, set)):
        for item in value:
            collect_numbers(item, found)
        return found
    return found


def _add_variants(into: set[float], value: float) -> None:
    into.add(value)
    into.add(abs(value))
    into.add(value * 100.0)
    into.add(abs(value) * 100.0)
    for scale in (1e-3, 1e-6, 1e-9):
        into.add(value * scale)
        into.add(abs(value) * scale)


def _matches(candidate: float, allowed: Iterable[float]) -> bool:
    for value in allowed:
        if candidate == value:
            return True
        if _rounds_same(candidate, value):
            return True
    return False


def _round_significant(value: float, digits: int = SIGNIFICANT_DIGITS) -> float:
    if value == 0.0:
        return 0.0
    exponent = floor(log10(abs(value)))
    factor = 10 ** (digits - 1 - exponent)
    return round(value * factor) / factor


def _rounds_same(candidate: float, value: float) -> bool:
    if value == 0.0:
        return abs(candidate) < 1e-12
    if abs(candidate - value) <= abs(value) * RELATIVE_TOLERANCE:
        return True
    return _round_significant(candidate) == _round_significant(value)


def _masked(text: str) -> str:
    masked = DATE_PATTERN.sub(lambda match: "#" * len(match.group(0)), text)
    masked = RULE_PATTERN.sub(lambda match: "#" * len(match.group(0)), masked)
    return WELL_PATTERN.sub(lambda match: "#" * len(match.group(0)), masked)


def unsupported_numbers(text: str, allowed: Iterable[float]) -> list[str]:
    allowed_values = list(allowed)
    masked = _masked(text)
    unsupported: list[str] = []
    for match in NUMBER_PATTERN.finditer(masked):
        raw = text[match.start() : match.end()]
        value = _to_float(raw)
        if value is None:
            continue
        if not _matches(value, allowed_values):
            unsupported.append(raw)
    return unsupported


def _strip(text: str, raw: str) -> str:
    stripped = text.replace(raw, "", 1)
    stripped = re.sub(r"\s{2,}", " ", stripped)
    stripped = re.sub(r"\s+([,.;:!?])", r"\1", stripped)
    return stripped.strip()


def guard_caption(
    text: str, tool_payloads: Sequence[Any]
) -> GuardResult:
    allowed: set[float] = set()
    for payload in tool_payloads:
        collect_numbers(payload, allowed)
    unsupported = unsupported_numbers(text, allowed)
    if not unsupported:
        return GuardResult(text=text.strip(), ok=True, dropped=())
    cleaned = text
    for raw in unsupported:
        cleaned = _strip(cleaned, raw)
    return GuardResult(text=cleaned, ok=False, dropped=tuple(unsupported))
