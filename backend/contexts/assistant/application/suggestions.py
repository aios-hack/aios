from __future__ import annotations

from typing import Any, Sequence

from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore
from backend.contexts.assistant.application.tools.context import ConsoleContext

SUGGESTION_COUNT = 4
BASE_SCENARIO = "base"
QUESTION_LIMIT = 90
FOLLOW_UPS_RU: dict[str, str] = {
    "doc": "А где это в коде?",
    "system-map": "Что делает суррогат?",
    "run": "Сравни с чемпионом",
    "run-list": "Сравни с чемпионом",
    "status-board": "Почему этот прогон чемпион?",
    "compare": "Откуда взялась разница?",
    "council": "Почему вето?",
    "rule": "Где это правило видно на экране?",
    "physics": "Какой инвариант держит отклик?",
    "constraints": "Что будет, если ограничение нарушить?",
    "pattern": "Что с этим делать?",
}
FOLLOW_UPS_EN: dict[str, str] = {
    "doc": "Where is this in the code?",
    "system-map": "What does the surrogate do?",
    "run": "Compare it with the champion",
    "run-list": "Compare it with the champion",
    "status-board": "Why is this run the champion?",
    "compare": "Where does the difference come from?",
    "council": "Why the veto?",
    "rule": "Where is this rule visible on screen?",
    "physics": "Which invariant holds the response?",
    "constraints": "What happens if the constraint is broken?",
    "pattern": "What should be done about it?",
}
CONTINUE_RU = "Вернись к вопросу «{question}»"
CONTINUE_EN = 'Go back to the question "{question}"'
DEFAULTS_RU: tuple[str, ...] = (
    "Как устроена система?",
    "Что с фондом сейчас?",
    "Кто тянет ЧДД вниз?",
    "Что такое ЧДД?",
)
DEFAULTS_EN: tuple[str, ...] = (
    "How is the system built?",
    "How is the field doing now?",
    "Who drags NPV down?",
    "What is NPV?",
)


def _trim(question: str) -> str:
    text = " ".join(str(question or "").split())
    if len(text) <= QUESTION_LIMIT:
        return text
    return text[: QUESTION_LIMIT - 1].rstrip() + "…"


def _follow_ups(card_types: Sequence[str], russian: bool) -> list[str]:
    table = FOLLOW_UPS_RU if russian else FOLLOW_UPS_EN
    collected: list[str] = []
    for card_type in card_types:
        text = table.get(str(card_type))
        if text and text not in collected:
            collected.append(text)
    return collected


def _continuation(history: Sequence[str], russian: bool) -> str | None:
    for question in reversed(list(history)[:-1]):
        trimmed = _trim(question)
        if trimmed:
            template = CONTINUE_RU if russian else CONTINUE_EN
            return template.format(question=trimmed)
    return None


def build_suggestions(
    console: ConsoleContext,
    store: ArtifactStore | None = None,
    card_types: Sequence[str] = (),
    history: Sequence[str] = (),
) -> list[dict[str, Any]]:
    russian = console.lang != "en"
    items: list[str] = _follow_ups(card_types, russian)
    continuation = _continuation(history, russian)
    if continuation is not None:
        items.append(continuation)
    well = console.selected_well
    if well:
        items.append(
            f"Почему скважина {well} так работает?"
            if russian
            else f"Why does well {well} behave this way?"
        )
        items.append(
            f"Кто связан со скважиной {well}?"
            if russian
            else f"Which wells are linked to well {well}?"
        )
    if store is not None and console.step is not None:
        try:
            index = store.scenario(console.scenario)
        except Exception:
            index = None
        if index is not None and console.step >= index.step_count() - 1:
            items.append(
                "Каким получился итог по ЧДД?" if russian else "What is the final NPV?"
            )
    if console.scenario and console.scenario != BASE_SCENARIO:
        items.append(
            f"Сравни {BASE_SCENARIO} и {console.scenario}"
            if russian
            else f"Compare {BASE_SCENARIO} and {console.scenario}"
        )
    if console.workspace and console.view:
        items.append(
            f"Что показывает экран {console.workspace}/{console.view}?"
            if russian
            else f"What does the {console.workspace}/{console.view} screen show?"
        )
    for fallback in DEFAULTS_RU if russian else DEFAULTS_EN:
        if len(items) >= SUGGESTION_COUNT:
            break
        if fallback not in items:
            items.append(fallback)
    unique: list[str] = []
    for item in items:
        if item and item not in unique:
            unique.append(item)
    return [{"text": text} for text in unique[:SUGGESTION_COUNT]]


__all__ = ["SUGGESTION_COUNT", "build_suggestions"]
