from __future__ import annotations

from typing import Any, Mapping

from backend.application.jarvis.tools.context import Card, ToolContext, ToolFailure

GENERAL_NOTICE_RU = (
    "Термина нет в курируемой базе проекта: ответ основан на общих знаниях "
    "модели, а не на данных фонда."
)
GENERAL_NOTICE_EN = (
    "The term is not in the project's curated base: the answer rests on the "
    "model's general knowledge, not on field data."
)


def _knowledge(context: ToolContext) -> Any:
    if context.knowledge is None:
        raise ToolFailure(
            "the Jarvis knowledge base is not loaded: there is nothing to answer "
            "term or screen questions from, check the directory "
            "frontend/public/jarvis/knowledge"
        )
    return context.knowledge


def explain_term(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    knowledge = _knowledge(context)
    query = str(arguments["query"]).strip()
    if not query:
        raise ToolFailure(
            "the term query is empty: there is nothing to look up in the "
            "knowledge base"
        )
    lang = str(arguments.get("lang") or context.lang)
    found = knowledge.find_term(query)
    if found is None:
        payload = {
            "id": None,
            "term": query,
            "definition": None,
            "formula": None,
            "unit": None,
            "source": None,
            "where_in_platform": [],
            "related": [],
            "provenance": "general",
            "notice": GENERAL_NOTICE_RU if lang == "ru" else GENERAL_NOTICE_EN,
        }
        return Card(
            type="glossary",
            title=query,
            payload=payload,
            provenance="general",
        )
    payload = found.as_payload(lang)
    return Card(
        type="glossary",
        title=str(payload["term"]),
        payload=payload,
        provenance="knowledge",
    )


def platform_guide(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    knowledge = _knowledge(context)
    lang = str(arguments.get("lang") or context.lang)
    workspace = arguments.get("workspace") or context.console.workspace
    view = arguments.get("view") or context.console.view
    query = arguments.get("query")
    screen = None
    if workspace and view:
        screen = knowledge.screen(str(workspace), str(view))
    if screen is None and query:
        screen = knowledge.find_screen(str(query))
    if screen is None and workspace:
        screen = knowledge.find_screen(str(workspace))
    if screen is None:
        raise ToolFailure(
            "no such screen exists in the console: the guide only covers the "
            "workspace/view pairs declared in ConsoleContext, and Jarvis does "
            "not invent routes"
        )
    payload = screen.as_payload(lang)
    return Card(
        type="guide",
        title=str(payload["title"]),
        payload=payload,
        provenance="knowledge",
    )
