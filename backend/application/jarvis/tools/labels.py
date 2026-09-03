from __future__ import annotations

from typing import Mapping

METRIC_UNITS: Mapping[str, str] = {
    "liquid_rate": "m3/day",
    "injection_rate": "m3/day",
    "watercut": "fraction",
    "bhp": "bar",
    "npv": "RUB",
    "active_wells": "wells",
    "production": "m3/day",
    "injection": "m3/day",
    "compensation": "fraction",
    "npv_cumulative": "RUB",
}

METRIC_LABELS: Mapping[str, Mapping[str, str]] = {
    "liquid_rate": {"ru": "дебит жидкости", "en": "liquid rate"},
    "injection_rate": {"ru": "закачка", "en": "injection"},
    "watercut": {"ru": "обводнённость", "en": "water cut"},
    "bhp": {"ru": "забойное давление", "en": "bottomhole pressure"},
    "npv": {"ru": "ЧДД", "en": "NPV"},
    "active_wells": {"ru": "действующий фонд", "en": "active well stock"},
    "production": {"ru": "добыча жидкости", "en": "liquid production"},
    "injection": {"ru": "закачка", "en": "injection"},
    "compensation": {"ru": "компенсация", "en": "compensation"},
    "npv_cumulative": {"ru": "накопленный ЧДД", "en": "cumulative NPV"},
}

EVENT_LABELS: Mapping[str, Mapping[str, str]] = {
    "COMMISSIONED": {"ru": "ввод", "en": "commissioned"},
    "ROLE_CHANGE": {"ru": "перевод в нагнетательные", "en": "converted to injection"},
    "SHUT": {"ru": "остановка", "en": "shut in"},
}

RULE_NAMES: Mapping[str, Mapping[str, str]] = {
    "R0": {"ru": "Порог рентабельности", "en": "Profitability threshold"},
    "R1": {"ru": "Ценность закачки", "en": "Value of injection"},
    "R2": {"ru": "Разгон чистых, придушивание обводнённых", "en": "Speed up clean, throttle watered"},
    "R3": {"ru": "Остановка после месяцев убытка", "en": "Shut in after months in loss"},
    "R4": {"ru": "Граница типоразмера ЭЦН", "en": "ESP size boundary"},
    "R5": {"ru": "Коридор компенсации участка", "en": "Area compensation corridor"},
    "R6": {"ru": "Перевод в нагнетательные", "en": "Conversion to injection"},
    "R7": {"ru": "Циклика высокообводнённых", "en": "Cycling heavily watered wells"},
}

TITLES: Mapping[str, Mapping[str, str]] = {
    "well": {"ru": "Скважина {well}", "en": "Well {well}"},
    "series": {"ru": "{label} — скважина {well}", "en": "{label} — well {well}"},
    "field": {"ru": "Фонд на {date}", "en": "Field on {date}"},
    "events": {"ru": "События фонда: {a} — {b}", "en": "Field events: {a} — {b}"},
    "rank_asc": {"ru": "{count} худших по {label}", "en": "{count} worst by {label}"},
    "rank_desc": {"ru": "{count} лучших по {label}", "en": "{count} best by {label}"},
    "rule": {"ru": "Правило {rule} — скважина {well}", "en": "Rule {rule} — well {well}"},
    "rule_one": {"ru": "Вклад правила {rule}", "en": "Contribution of rule {rule}"},
    "rule_all": {"ru": "Вклад правил в ЧДД", "en": "Rule contributions to NPV"},
    "connectivity": {"ru": "Связи скважины {well}", "en": "Links of well {well}"},
    "compare": {"ru": "{a} против {b}", "en": "{a} versus {b}"},
    "patterns_well": {"ru": "Находки по скважине {well}", "en": "Findings for well {well}"},
    "patterns_field": {"ru": "Диагностические находки", "en": "Diagnostic findings"},
    "tool_failed": {"ru": "Не удалось: {tool}", "en": "Tool failed: {tool}"},
}


def pick(table: Mapping[str, Mapping[str, str]], key: str, lang: str) -> str:
    entry = table.get(key)
    if entry is None:
        return key
    return entry.get(lang, entry.get("ru", key))


def title(key: str, lang: str, **values: object) -> str:
    template = pick(TITLES, key, lang)
    return template.format(**values)
