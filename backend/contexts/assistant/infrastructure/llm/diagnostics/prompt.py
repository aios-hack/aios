from __future__ import annotations

from typing import Sequence

from backend.contexts.assistant.infrastructure.llm.diagnostics.model import (
    Finding,
    TextClient,
)


def _format_finding(finding: Finding) -> str:
    parts = [
        f"паттерн: {finding.name_ru}",
        f"скважина: {finding.well}",
        f"важность: {finding.severity}",
    ]
    if finding.control_step is not None:
        parts.append(f"шаг управления: {finding.control_step}")
    if finding.window is not None:
        parts.append(f"окно: с {finding.window[0]} по {finding.window[1]}")
    values = ", ".join(f"{name}={value}" for name, value in finding.inputs.items())
    parts.append(f"числа: {values}")
    return "- " + "; ".join(parts)


def build_diagnosis_prompt(findings: Sequence[Finding], locale: str = "ru") -> str:
    if locale != "ru":
        raise ValueError(f"unsupported locale: {locale}")
    if not findings:
        raise ValueError("no findings: there is nothing to build the diagnostician prompt from")
    lines = [
        "Ты — инженер-технолог нефтепромысла. Ниже перечислены находки",
        "детерминированных детекторов по артефакту прогона. Все числа уже",
        "посчитаны и приведены в находках. Сформулируй диагноз на языке",
        "промысла: назови проблему по каждой находке и её вероятную причину.",
        "Запрещено придумывать, пересчитывать или округлять числа —",
        "используй только приведённые значения и не добавляй новых.",
        "",
        "Находки:",
    ]
    lines.extend(_format_finding(finding) for finding in findings)
    return "\n".join(lines)


def diagnose(
    findings: Sequence[Finding], client: TextClient, locale: str = "ru"
) -> str:
    return client.complete(build_diagnosis_prompt(findings, locale))
