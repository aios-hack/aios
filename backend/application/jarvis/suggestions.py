from __future__ import annotations

from typing import Any

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.tools.context import ConsoleContext

SUGGESTION_COUNT = 3
BASE_SCENARIO = "base"
DEFAULTS_RU: tuple[str, ...] = (
    "Что с фондом сейчас?",
    "Кто тянет ЧДД вниз?",
    "Что такое ЧДД?",
)
DEFAULTS_EN: tuple[str, ...] = (
    "How is the field doing now?",
    "Who drags NPV down?",
    "What is NPV?",
)


def build_suggestions(
    console: ConsoleContext, store: ArtifactStore | None = None
) -> list[dict[str, Any]]:
    russian = console.lang != "en"
    items: list[str] = []
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
        if item not in unique:
            unique.append(item)
    return [{"text": text} for text in unique[:SUGGESTION_COUNT]]
