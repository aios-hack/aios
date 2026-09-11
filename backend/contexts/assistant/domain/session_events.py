from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["restore_exchanges"]


def restore_exchanges(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in events:
        kind = event.get("type")
        if kind == "ask":
            if current is not None:
                collected.append(current)
            current = {
                "question": str(event.get("question") or ""),
                "card_types": [],
                "caption": "",
                "answer": "",
            }
        elif current is None:
            continue
        elif kind == "card":
            card = event.get("card") or {}
            if isinstance(card, Mapping):
                current["card_types"].append(str(card.get("type") or ""))
        elif kind == "caption":
            current["caption"] = str(event.get("text") or "")
        elif kind == "answer":
            current["answer"] = str(event.get("text") or "")
    if current is not None:
        collected.append(current)
    return collected
