from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.contexts.assistant.application.answer import ANSWER_MARKER
from backend.contexts.assistant.infrastructure.system_map import SystemMap
from backend.contexts.assistant.domain.console_context import ConsoleContext
from backend.shared.json_io import read_json

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_FILE = "prompt.json"
PROMPT_LANG = "ru"
DEFAULT_LANG = "ru"
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


class PromptResources:
    def __init__(self, lang: str = PROMPT_LANG) -> None:
        payload = read_json(PROMPTS_DIR / lang / PROMPT_FILE)
        if not isinstance(payload, dict):
            raise TypeError(f"prompt resource {lang}: an object is expected")
        self._payload: Mapping[str, Any] = payload

    def lines(self, key: str) -> tuple[str, ...]:
        return tuple(str(item) for item in self._payload[key])

    def section(self, key: str) -> str:
        return str(self._payload["sections"][key])

    def context_label(self, key: str) -> str:
        return str(self._payload["context_labels"][key])

    def live_label(self, key: str) -> str:
        return str(self._payload["live_labels"][key])

    def language_name(self, lang: str) -> str:
        names = self._payload["language_names"]
        return str(names.get(lang, names[DEFAULT_LANG]))


PROMPT_TEXT = PromptResources()


def format_rules(lang: str) -> tuple[str, ...]:
    return tuple(
        template.format(
            max_caption_sentences=MAX_CAPTION_SENTENCES,
            answer_marker=ANSWER_MARKER,
            answer_limit=ANSWER_LIMIT,
        )
        for template in PROMPT_TEXT.lines("format_rules")
    )


def context_lines(console: ConsoleContext) -> list[str]:
    lines = [PROMPT_TEXT.context_label("scenario").format(value=console.scenario)]
    if console.step is not None:
        lines.append(PROMPT_TEXT.context_label("step").format(value=console.step))
    if console.date is not None:
        lines.append(PROMPT_TEXT.context_label("date").format(value=console.date))
    if console.selected_well is not None:
        lines.append(
            PROMPT_TEXT.context_label("selected_well").format(
                value=console.selected_well
            )
        )
    if console.workspace is not None and console.view is not None:
        lines.append(
            PROMPT_TEXT.context_label("screen").format(
                workspace=console.workspace, view=console.view
            )
        )
    return lines


def live_lines(live: Mapping[str, Any] | None) -> list[str]:
    if not live:
        return []
    lines: list[str] = []
    champion = live.get("champion")
    if isinstance(champion, Mapping) and champion.get("recorded"):
        lines.append(
            PROMPT_TEXT.live_label("champion").format(
                schedule_hash=str(champion.get("schedule_hash"))[:12],
                npv=champion.get("opm_npv_rub"),
                sound=champion.get("sound"),
            )
        )
    last = live.get("last_run")
    if isinstance(last, Mapping) and last.get("recorded"):
        lines.append(
            PROMPT_TEXT.live_label("last_run").format(
                run_id=last.get("run_id"),
                status=last.get("status"),
                verified_npv=last.get("verified_npv"),
            )
        )
    elif isinstance(last, Mapping) and last.get("reason"):
        lines.append(PROMPT_TEXT.live_label("no_runs").format(reason=last["reason"]))
    alerts = live.get("alerts")
    if isinstance(alerts, Sequence) and alerts:
        item = PROMPT_TEXT.live_label("alert_item")
        listed = ", ".join(
            item.format(
                name=row.get("name"), well=row.get("well"), step=row.get("step")
            )
            for row in alerts
            if isinstance(row, Mapping)
        )
        lines.append(PROMPT_TEXT.live_label("alerts").format(listed=listed))
    return lines


def about_lines(system: SystemMap | None, lang: str) -> list[str]:
    fallback = list(PROMPT_TEXT.lines("fallback_about"))
    if system is None:
        return fallback
    lines = system.brief(lang, BRIEF_NODES)
    return lines if lines else fallback


def build_system_prompt(
    console: ConsoleContext,
    lang: str = DEFAULT_LANG,
    system: SystemMap | None = None,
    live: Mapping[str, Any] | None = None,
    memory: str = "",
) -> str:
    language = PROMPT_TEXT.language_name(lang)
    parts: list[str] = list(PROMPT_TEXT.lines("role"))
    parts.append(PROMPT_TEXT.section("about"))
    parts.extend(f"- {line}" for line in about_lines(system, lang))
    parts.append(PROMPT_TEXT.section("console_context"))
    parts.extend(context_lines(console))
    live_block = live_lines(live)
    if live_block:
        parts.append(PROMPT_TEXT.section("live_state"))
        parts.extend(live_block)
    parts.append(PROMPT_TEXT.section("defaults_notice"))
    parts.append(PROMPT_TEXT.section("playbook"))
    parts.extend(f"- {line}" for line in PROMPT_TEXT.lines("playbook"))
    parts.append(PROMPT_TEXT.section("format"))
    parts.extend(f"- {line}" for line in format_rules(lang))
    parts.append(PROMPT_TEXT.section("rules"))
    parts.extend(f"- {line}" for line in PROMPT_TEXT.lines("rules"))
    if memory:
        parts.append(PROMPT_TEXT.section("memory"))
        parts.append(memory)
    parts.append(PROMPT_TEXT.section("language_line").format(language=language))
    return "\n".join(parts)
