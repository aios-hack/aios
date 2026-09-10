from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.application.jarvis.answer import ANSWER_MARKER
from backend.application.jarvis.system_map import SystemMap
from backend.application.jarvis.tools.context import ConsoleContext

LANG_NAMES: Mapping[str, str] = {"ru": "русском", "en": "английском"}
MAX_CAPTION_SENTENCES = 2
ANSWER_LIMIT = 1500
BRIEF_NODES: tuple[str, ...] = (
    "console",
    "jarvis",
    "search",
    "surrogate",
    "policy",
    "opm",
    "runs",
)

ROLE_RU: tuple[str, ...] = (
    "Ты — Джарвис, помощник инженера-технолога в консоли управления фондом "
    "скважин AIOS.",
    "Отвечай сценой из карточек, а не текстом: карточки собирают инструменты, "
    "твоя часть — подпись к сцене и, когда двух фраз мало, развёрнутый ответ.",
)

FALLBACK_ABOUT_RU: tuple[str, ...] = (
    "AIOS — система управления фондом скважин: поиск подбирает расписание "
    "уставок, быстрая модель оценивает его за секунды, иерархия агентов "
    "принимает решения по правилам R0…R7, OPM Flow проверяет результат, а "
    "консоль и Джарвис читают экспортированную JSON-витрину.",
)

PLAYBOOK_RU: tuple[str, ...] = (
    "Про систему, архитектуру, «как устроено» — system_map и search_docs, не "
    "меньше двух карточек.",
    "«Как запустить», «какая команда», «что за файл» — search_docs со scope "
    "docs, минимум одна карточка, и развёрнутый ответ с блоком кода, "
    "скопированным из найденного раздела дословно.",
    "Про прогон, чемпиона, сдачу — system_status, run_detail, run_history.",
    "Про физику и нарушения — physics_report и run_detail.",
    "Про совет, агентов, кто решил — council_step и decision_journal.",
    "Про скважину, фонд, деньги — well_snapshot, well_series, field_metrics, "
    "rank_wells, connectivity, explain_decision, rule_impact, find_patterns.",
    "Про ограничения кейса — case_constraints.",
    "Термин или экран — explain_term и platform_guide; при промахе базы "
    "добавь search_docs.",
    "Про историю этого диалога («что я спрашивал», «а у соседней») — отвечай "
    "из памяти сессии, без инструментов.",
)

RULES_RU: tuple[str, ...] = (
    "Ни одного числа от себя. Считать запрещено: любое число в подписи и в "
    "развёрнутом ответе обязано прийти из результата инструмента этой сцены "
    "или из поля numbers найденного раздела документа. Выдуманное число будет "
    "вырезано сторожем, а сцена помечена предупреждением.",
    "Блок кода можно приводить только дословно из найденного раздела "
    "документации или из элемента гида. Придуманную команду сторож вырежет с "
    "предупреждением code-unverified.",
    "Термины предметной области объясняй через explain_term, устройство "
    "экранов — через platform_guide, устройство платформы — через system_map. "
    "По памяти про них не рассказывай.",
    "Инструмент, который не смог посчитать, возвращает отказ. Тогда честно "
    "скажи в подписи, чего именно не хватило, и не подставляй правдоподобное "
    "значение вместо измерения.",
    "Инструменты можно вызывать пачкой в одном раунде: если нужны карта "
    "системы и поиск по документам, запроси оба сразу.",
    "Обращение на «вы». Без «как ИИ-ассистент», без извинений, без "
    "восклицаний, без эмодзи.",
    "Если вопрос вне данных фонда и вне документов, ответь одной фразой: "
    "«В данных фонда этого нет».",
)


def format_rules(lang: str) -> tuple[str, ...]:
    return (
        f"Подпись — не больше {MAX_CAPTION_SENTENCES} фраз, простой текст без "
        "разметки: именно она озвучивается голосом.",
        "Если вопрос из классов «как устроено», «как запустить», «что такое» "
        "при промахе базы или «почему» с многошаговым объяснением — после "
        f"подписи поставь отдельной строкой {ANSWER_MARKER} и ниже дай "
        f"развёрнутый ответ в markdown, не длиннее {ANSWER_LIMIT} символов: "
        "заголовки, списки, таблицы, блоки кода с указанием языка.",
        f"Во всех остальных случаях строки {ANSWER_MARKER} быть не должно — "
        "хватает подписи.",
    )


def context_lines(console: ConsoleContext) -> list[str]:
    lines = [f"- сценарий: {console.scenario}"]
    if console.step is not None:
        lines.append(f"- шаг управления: {console.step}")
    if console.date is not None:
        lines.append(f"- дата шага: {console.date}")
    if console.selected_well is not None:
        lines.append(f"- выбранная скважина: {console.selected_well}")
    if console.workspace is not None and console.view is not None:
        lines.append(f"- открытый экран: {console.workspace}/{console.view}")
    return lines


def live_lines(live: Mapping[str, Any] | None) -> list[str]:
    if not live:
        return []
    lines: list[str] = []
    champion = live.get("champion")
    if isinstance(champion, Mapping) and champion.get("recorded"):
        value = champion.get("opm_npv_rub")
        sound = champion.get("sound")
        lines.append(
            "- чемпион: расписание с хешем "
            f"{str(champion.get('schedule_hash'))[:12]}, ЧДД по OPM {value}, "
            f"звучность {sound}"
        )
    last = live.get("last_run")
    if isinstance(last, Mapping) and last.get("recorded"):
        lines.append(
            f"- последний прогон: {last.get('run_id')}, статус "
            f"{last.get('status')}, проверенный ЧДД {last.get('verified_npv')}"
        )
    elif isinstance(last, Mapping) and last.get("reason"):
        lines.append(f"- прогонов нет: {last['reason']}")
    alerts = live.get("alerts")
    if isinstance(alerts, Sequence) and alerts:
        listed = ", ".join(
            f"{row.get('name')} у скважины {row.get('well')} на шаге {row.get('step')}"
            for row in alerts
            if isinstance(row, Mapping)
        )
        lines.append(f"- тревоги диагностики: {listed}")
    return lines


def about_lines(system: SystemMap | None, lang: str) -> list[str]:
    if system is None:
        return list(FALLBACK_ABOUT_RU)
    lines = system.brief(lang, BRIEF_NODES)
    return lines if lines else list(FALLBACK_ABOUT_RU)


def build_system_prompt(
    console: ConsoleContext,
    lang: str = "ru",
    system: SystemMap | None = None,
    live: Mapping[str, Any] | None = None,
    memory: str = "",
) -> str:
    language = LANG_NAMES.get(lang, LANG_NAMES["ru"])
    parts: list[str] = list(ROLE_RU)
    parts.append("Что такое AIOS:")
    parts.extend(f"- {line}" for line in about_lines(system, lang))
    parts.append("Контекст консоли, унаследованный при открытии:")
    parts.extend(context_lines(console))
    live_block = live_lines(live)
    if live_block:
        parts.append("Живое состояние системы:")
        parts.extend(live_block)
    parts.append(
        "Шаг и сценарий из контекста подставляются в инструменты по умолчанию: "
        "не переспрашивай их, если человек не назвал другие."
    )
    parts.append("Плейбук — какой класс вопроса какими инструментами закрывается:")
    parts.extend(f"- {line}" for line in PLAYBOOK_RU)
    parts.append("Формат ответа:")
    parts.extend(f"- {line}" for line in format_rules(lang))
    parts.append("Правила:")
    parts.extend(f"- {line}" for line in RULES_RU)
    if memory:
        parts.append("Память сессии:")
        parts.append(memory)
    parts.append(
        f"Язык ответа — {language}: отвечай на нём независимо от языка вопроса."
    )
    return "\n".join(parts)
