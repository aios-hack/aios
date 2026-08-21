from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from aios_backend.core.contracts import Role, RunArtifact, Schedule, TraceEntry

from aios_backend.infrastructure.llm.diagnostics import TextClient

_ROLE_RU = {
    Role.PROD: "добывающая",
    Role.INJ: "нагнетательная",
    Role.NONE: "без роли",
}


@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    well: str
    control_step: int
    rule: str
    inputs: dict[str, float]
    decision: str
    why: str


def _find_entry(
    trace_entries: Sequence[TraceEntry], well: str, control_step: int
) -> TraceEntry:
    for entry in trace_entries:
        if entry.well == well and entry.control_step == control_step:
            return entry
    raise LookupError(
        f"в Trace нет записи для скважины {well} на шаге {control_step}: "
        "без записи объяснять нечего, реконструкция решения невозможна"
    )


def _well_role_ru(schedule: Schedule, well: str) -> str:
    state = schedule.initial_state.get(well)
    if state is None:
        return _ROLE_RU[Role.NONE]
    return _ROLE_RU[state.role]


def _build_why(entry: TraceEntry, role_ru: str) -> str:
    facts = ", ".join(f"{name}={value}" for name, value in entry.inputs.items())
    return (
        f"Скважина {entry.well} ({role_ru}). На шаге {entry.control_step} "
        f"сработало правило {entry.rule.value}: правило прочитало фактические "
        f"величины ({facts}) и по своему условию приняло решение "
        f"«{entry.decision}». Причина решения — именно эти значения на входе "
        f"правила {entry.rule.value}, других источников у решения нет."
    )


def explain_decision(
    trace_entries: Sequence[TraceEntry],
    well: str,
    control_step: int,
    schedule: Schedule,
    locale: str = "ru",
) -> DecisionExplanation:
    if locale != "ru":
        raise ValueError(f"неподдерживаемая локаль: {locale}")
    entry = _find_entry(trace_entries, well, control_step)
    role_ru = _well_role_ru(schedule, well)
    return DecisionExplanation(
        well=entry.well,
        control_step=entry.control_step,
        rule=entry.rule.value,
        inputs=dict(entry.inputs),
        decision=entry.decision,
        why=_build_why(entry, role_ru),
    )


def build_explanation_prompt(
    explanation: DecisionExplanation, locale: str = "ru"
) -> str:
    if locale != "ru":
        raise ValueError(f"неподдерживаемая локаль: {locale}")
    facts = ", ".join(
        f"{name}={value}" for name, value in explanation.inputs.items()
    )
    lines = [
        "Ты — инженер-технолог нефтепромысла. Объясни решение системы",
        "управления так, чтобы его понял промысловый инженер.",
        "Требования к объяснению:",
        "- объясни причинно-следственную связь: какие фактические величины",
        "  привели к срабатыванию правила и почему из них следует решение;",
        "- явно сошлись на сработавшее правило;",
        "- пиши на языке промысла, а не пересказывай числа списком;",
        "- запрещено выдумывать, пересчитывать или добавлять новые числа —",
        "  используй только приведённые ниже значения.",
        "",
        "Факты решения:",
        f"- скважина: {explanation.well}",
        f"- шаг управления: {explanation.control_step}",
        f"- правило: {explanation.rule}",
        f"- входы правила: {facts}",
        f"- решение: {explanation.decision}",
        f"- реконструкция: {explanation.why}",
    ]
    return "\n".join(lines)


def explain(
    trace_entries: Sequence[TraceEntry],
    well: str,
    control_step: int,
    schedule: Schedule,
    client: TextClient,
    locale: str = "ru",
) -> str:
    explanation = explain_decision(trace_entries, well, control_step, schedule, locale)
    return client.complete(build_explanation_prompt(explanation, locale))


def export_explanations_json(
    artifact: RunArtifact,
    out_path: str | Path,
    client: TextClient | None = None,
) -> Path:
    items = []
    for entry in artifact.trace:
        explanation = explain_decision(
            artifact.trace, entry.well, entry.control_step, artifact.schedule
        )
        item = asdict(explanation)
        if client is None:
            item["text"] = None
        else:
            item["text"] = client.complete(build_explanation_prompt(explanation))
        items.append(item)
    path = Path(out_path)
    path.write_text(
        json.dumps(items, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return path
